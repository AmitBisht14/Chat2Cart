import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import monotonic

import structlog
from pydantic import BaseModel, TypeAdapter

from chat2cart.db.connection import connect
from chat2cart.logging import redact_value
from chat2cart.swiggy.oauth import utc_now
from chat2cart.understanding.schemas import ResolvedItem

POLL_INTERVAL_SECONDS = 1.0
ERROR_MAX_LENGTH = 500

JobHandler = Callable[[str, dict[str, object]], None]

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


class MergePayload(BaseModel):
    items: list[ResolvedItem]


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
) -> bool:
    """Run the oldest pending job. Returns False when nothing is pending.

    A failing job is marked failed and this returns normally, so the next job still runs.
    """
    claimed = conn.execute(CLAIM_NEXT, (clock().isoformat(),)).fetchone()
    conn.commit()
    if claimed is None:
        return False
    job_id: int = claimed["id"]
    started = monotonic()
    error = _run_handler(handler, claimed["source"], claimed["payload_json"])
    status = "done" if error is None else "failed"
    conn.execute(FINISH, (status, clock().isoformat(), error, job_id))
    conn.commit()
    structlog.get_logger().info(
        "cart_job_finished", job_id=job_id, status=status, seconds=round(monotonic() - started, 3)
    )
    return True


def reset_running_jobs(conn: sqlite3.Connection) -> None:
    """Jobs left running by a crash go back to pending."""
    conn.execute(RESET_RUNNING)
    conn.commit()


def merge_job_handler(run_merge: Callable[[list[ResolvedItem]], object]) -> JobHandler:
    """A handler that merges the job's resolved items into the Swiggy cart."""

    def handle(_source: str, payload: dict[str, object]) -> None:
        run_merge(MergePayload.model_validate(payload).items)

    return handle


class CartWorker:
    """One background thread that runs cart jobs one after another, oldest first."""

    def __init__(self, db_path: Path, handler: JobHandler, poll_interval: float) -> None:
        self._db_path = db_path
        self._handler = handler
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cart-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        # SQLite connections stay on the thread that made them, so the worker opens its own.
        with closing(connect(self._db_path)) as conn:
            reset_running_jobs(conn)
            while not self._stop.is_set():
                if not self._run_one(conn):
                    self._stop.wait(self._poll_interval)

    def _run_one(self, conn: sqlite3.Connection) -> bool:
        try:
            return run_next_job(conn, self._handler)
        except sqlite3.Error as error:
            structlog.get_logger().error("cart_worker_db_error", error_type=type(error).__name__)
            return False


def start_cart_worker(
    db_path: Path, handler: JobHandler, poll_interval: float = POLL_INTERVAL_SECONDS
) -> CartWorker:
    worker = CartWorker(db_path, handler, poll_interval)
    worker.start()
    return worker


def _run_handler(handler: JobHandler, source: str, payload_json: str) -> str | None:
    """Run the handler. Returns None on success, else the error text to store."""
    try:
        handler(source, PAYLOAD.validate_json(payload_json))
    except Exception as error:
        # A job can fail in any way; it is recorded on the row and the next job still runs.
        structlog.get_logger().error("cart_job_failed", error_type=type(error).__name__)
        return _error_text(error)
    return None


def _error_text(error: Exception) -> str:
    text = str(redact_value(f"{type(error).__name__}: {error}"))
    return text[:ERROR_MAX_LENGTH]
