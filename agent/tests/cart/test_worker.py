import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from chat2cart.cart.worker import (
    ERROR_MAX_LENGTH,
    enqueue_job,
    run_next_job,
    start_cart_worker,
)
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate

POLL = 0.01
WAIT_SECONDS = 5.0


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    conn = connect(tmp_path / "chat2cart.sqlite")
    migrate(conn)
    conn.close()
    return tmp_path / "chat2cart.sqlite"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    yield connection
    connection.close()


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(POLL)


def job_rows(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as reader:
        return reader.execute("SELECT * FROM cart_jobs ORDER BY id").fetchall()


def statuses(db_path: Path) -> list[str]:
    return [row["status"] for row in job_rows(db_path)]


def test_enqueue_stores_a_pending_job_with_its_source_and_payload(conn: sqlite3.Connection) -> None:
    job_id = enqueue_job(conn, "overnight", {"items": []})

    (row,) = conn.execute("SELECT * FROM cart_jobs WHERE id = ?", (job_id,)).fetchall()

    assert (row["source"], row["status"], json.loads(row["payload_json"])) == (
        "overnight",
        "pending",
        {"items": []},
    )
    assert row["created_at"]


def test_two_concurrent_requests_are_processed_in_order_without_overlap(db_path: Path) -> None:
    barrier = threading.Barrier(2)

    def enqueue(source: str) -> None:
        with connect(db_path) as writer:
            barrier.wait()
            enqueue_job(writer, source, {})

    threads = [threading.Thread(target=enqueue, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    intervals: list[tuple[str, float, float]] = []

    def handler(source: str, _payload: dict[str, object]) -> None:
        started = time.monotonic()
        time.sleep(0.05)
        intervals.append((source, started, time.monotonic()))

    worker = start_cart_worker(db_path, handler, POLL)
    wait_until(lambda: statuses(db_path) == ["done", "done"])
    worker.stop()

    stored_order = [row["source"] for row in job_rows(db_path)]
    assert [source for source, _, _ in intervals] == stored_order
    assert intervals[0][2] <= intervals[1][1]


def test_pending_jobs_survive_a_restart(db_path: Path) -> None:
    with connect(db_path) as first_process:
        enqueue_job(first_process, "one", {})
        enqueue_job(first_process, "two", {})
    handled: list[str] = []

    worker = start_cart_worker(db_path, lambda source, _payload: handled.append(source), POLL)
    wait_until(lambda: statuses(db_path) == ["done", "done"])
    worker.stop()

    assert handled == ["one", "two"]


def test_a_job_left_running_by_a_crash_is_run_again_after_restart(db_path: Path) -> None:
    with connect(db_path) as first_process:
        job_id = enqueue_job(first_process, "stuck", {})
        first_process.execute("UPDATE cart_jobs SET status = 'running' WHERE id = ?", (job_id,))
        first_process.commit()
    handled: list[str] = []

    worker = start_cart_worker(db_path, lambda source, _payload: handled.append(source), POLL)
    wait_until(lambda: statuses(db_path) == ["done"])
    worker.stop()

    assert handled == ["stuck"]


def test_a_failed_job_is_marked_failed_with_a_reason_and_the_next_job_still_runs(
    conn: sqlite3.Connection,
) -> None:
    enqueue_job(conn, "first", {})
    enqueue_job(conn, "second", {})

    def handler(source: str, _payload: dict[str, object]) -> None:
        if source == "first":
            raise ValueError("cannot merge")

    assert run_next_job(conn, handler) is True
    assert run_next_job(conn, handler) is True

    first, second = conn.execute("SELECT * FROM cart_jobs ORDER BY id").fetchall()
    assert (first["status"], first["error"]) == ("failed", "ValueError: cannot merge")
    assert (second["status"], second["error"]) == ("done", None)
    assert first["finished_at"] and second["finished_at"]


def test_the_stored_error_is_redacted_and_truncated(conn: sqlite3.Connection) -> None:
    enqueue_job(conn, "job", {})

    def handler(_source: str, _payload: dict[str, object]) -> None:
        raise RuntimeError("call failed with Bearer abc.def-123 " + "x" * 2000)

    run_next_job(conn, handler)

    error = conn.execute("SELECT error FROM cart_jobs").fetchone()["error"]
    assert "abc.def-123" not in error
    assert "Bearer [redacted]" in error
    assert len(error) == ERROR_MAX_LENGTH


def test_run_next_job_reports_false_when_nothing_is_pending(conn: sqlite3.Connection) -> None:
    assert run_next_job(conn, lambda _source, _payload: None) is False


def test_the_worker_keeps_running_jobs_after_one_fails(db_path: Path) -> None:
    with connect(db_path) as writer:
        enqueue_job(writer, "bad", {})
        enqueue_job(writer, "good", {})

    def handler(source: str, _payload: dict[str, object]) -> None:
        if source == "bad":
            raise ValueError("boom")

    worker = start_cart_worker(db_path, handler, POLL)
    wait_until(lambda: statuses(db_path) == ["failed", "done"])
    worker.stop()


def test_a_stopped_worker_is_no_longer_alive(db_path: Path) -> None:
    worker = start_cart_worker(db_path, lambda _source, _payload: None, POLL)

    worker.stop()

    assert worker.is_alive() is False
