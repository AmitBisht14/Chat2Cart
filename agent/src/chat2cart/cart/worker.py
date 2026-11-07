import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import monotonic

import structlog
from pydantic import TypeAdapter

from chat2cart.background import BackgroundLoop
from chat2cart.db.connection import connect
from chat2cart.logging import redact_value
from chat2cart.swiggy.oauth import utc_now

POLL_INTERVAL_SECONDS = 1.0
ERROR_MAX_LENGTH = 500

JobHandler = Callable[[str, dict[str, object]], None]
FailureHook = Callable[[sqlite3.Connection, Exception], None]

INSERT_JOB = (
    "INSERT INTO cart_jobs (source, payload_json, status, created_at) VALUES (?, ?, 'pending', ?)"
)
RESET_RUNNING = "UPDATE cart_jobs SET status = 'pending' WHERE status = 'running'"
CLAIM_NEXT = """
    UPDATE cart_jobs SET status = 'running', started_at = ?
    WHERE id = (SELECT id FROM cart_jobs WHERE status = 'pending' ORDER BY id LIMIT 1)
    RETURNING id, source, payload_json"""
FINISH = "UPDATE cart_jobs SET status = ?, finished_at = ?, error = ? WHERE id = ?"

PAYLOAD = TypeAdapter(dict[str, object])


def enqueue_job(
    conn: sqlite3.Connection,
    source: str,
    payload: dict[str, object],
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Store a cart job as pending. Jobs are rows, so they survive a restart."""
    cursor = conn.execute(INSERT_JOB, (source, json.dumps(payload), clock().isoformat()))
    conn.commit()
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("The cart job was not stored.")
    return cursor.lastrowid


def run_next_job(
    conn: sqlite3.Connection,
    handler: JobHandler,
    clock: Callable[[], datetime] = utc_now,
    on_failure: FailureHook | None = None,
) -> bool:
    """Run the oldest pending job. Returns False when nothing is pending.

    A failing job is marked failed and this returns normally, so the next job still runs.
    on_failure, if given, is told about the error (for an alert); it can never break the worker.
    """
    claimed = conn.execute(CLAIM_NEXT, (clock().isoformat(),)).fetchone()
    conn.commit()
    if claimed is None:
        return False
    job_id: int = claimed["id"]
    started = monotonic()
    failure = _run_handler(handler, claimed["source"], claimed["payload_json"])
    status = "done" if failure is None else "failed"
    error = None if failure is None else _error_text(failure)
    conn.execute(FINISH, (status, clock().isoformat(), error, job_id))
    conn.commit()
    if failure is not None and on_failure is not None:
        _tell(on_failure, conn, failure)
    structlog.get_logger().info(
        "cart_job_finished", job_id=job_id, status=status, seconds=round(monotonic() - started, 3)
    )
    return True


def reset_running_jobs(conn: sqlite3.Connection) -> None:
    """Jobs left running by a crash go back to pending."""
    conn.execute(RESET_RUNNING)
    conn.commit()


def start_cart_worker(
    db_path: Path,
    handler: JobHandler,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    on_failure: FailureHook | None = None,
) -> BackgroundLoop:
    """One background thread that runs cart jobs one after another, oldest first."""
    loop = BackgroundLoop(
        "cart-worker", lambda stop: _run_worker(db_path, handler, poll_interval, on_failure, stop)
    )
    loop.start()
    return loop


def _run_worker(
    db_path: Path,
    handler: JobHandler,
    poll_interval: float,
    on_failure: FailureHook | None,
    stop: threading.Event,
) -> None:
    # SQLite connections stay on the thread that made them, so the worker opens its own.
    with closing(connect(db_path)) as conn:
        reset_running_jobs(conn)
        while not stop.is_set():
            if not _run_one(conn, handler, on_failure):
                stop.wait(poll_interval)


def _run_one(conn: sqlite3.Connection, handler: JobHandler, on_failure: FailureHook | None) -> bool:
    try:
        return run_next_job(conn, handler, on_failure=on_failure)
    except sqlite3.Error as error:
        structlog.get_logger().error("cart_worker_db_error", error_type=type(error).__name__)
        return False


def _run_handler(handler: JobHandler, source: str, payload_json: str) -> Exception | None:
    """Run the handler. Returns None on success, else the error that stopped it."""
    try:
        handler(source, PAYLOAD.validate_json(payload_json))
    except Exception as error:
        # A job can fail in any way; it is recorded on the row and the next job still runs.
        structlog.get_logger().error("cart_job_failed", error_type=type(error).__name__)
        return error
    return None


def _tell(on_failure: FailureHook, conn: sqlite3.Connection, failure: Exception) -> None:
    try:
        on_failure(conn, failure)
    except Exception as error:
        # An alert that cannot be sent must not stop the worker.
        structlog.get_logger().error("failure_hook_failed", error_type=type(error).__name__)


def _error_text(error: Exception) -> str:
    text = str(redact_value(f"{type(error).__name__}: {error}"))
    return text[:ERROR_MAX_LENGTH]
