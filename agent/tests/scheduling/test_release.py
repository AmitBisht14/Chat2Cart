import json
import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes.window import Window

from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.db.repos import enqueue_request
from chat2cart.scheduling.release import (
    RELEASE_JOB_ID,
    build_scheduler,
    next_release_time,
    release_queue,
    release_trigger,
)
from chat2cart.understanding.schemas import ExtractedItem

IST = ZoneInfo("Asia/Kolkata")


def ist(hour: int, minute: int = 0, day: int = 7) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


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


def queue_overnight(conn: sqlite3.Connection, *inbound_ids: str) -> None:
    for inbound_id in inbound_ids:
        item = ExtractedItem(name="atta", quantity=Decimal(2), unit="kg", sources=[inbound_id])
        enqueue_request(conn, inbound_id, [item], clock=lambda: ist(23, 0, day=6))


def rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def test_the_release_fires_at_0700_ist_every_day() -> None:
    trigger = release_trigger(Window())

    assert trigger.get_next_fire_time(None, ist(3, 0)) == ist(7, 0)
    assert trigger.get_next_fire_time(ist(7, 0), ist(7, 0, 7)) == ist(7, 0, day=8)


def test_the_scheduler_has_one_release_job_that_still_fires_after_a_sleep() -> None:
    scheduler = build_scheduler(Window(), lambda: None)

    (job,) = scheduler.get_jobs()

    assert job.id == RELEASE_JOB_ID
    assert (job.coalesce, job.max_instances, job.misfire_grace_time) == (True, 1, None)
    assert str(job.trigger.timezone) == "Asia/Kolkata"


def test_the_release_at_0700_turns_each_queued_request_into_a_cart_job(
    conn: sqlite3.Connection,
) -> None:
    queue_overnight(conn, "m1", "m2")

    job_ids = release_queue(conn, ist(7, 0), Window())

    jobs = rows(conn, "cart_jobs")
    assert [job["id"] for job in jobs] == job_ids
    assert [(job["source"], job["status"]) for job in jobs] == [("queue", "pending")] * 2
    payload = json.loads(jobs[0]["payload_json"])
    assert (payload["inbound_ids"], payload["queue_ids"]) == (["m1"], [1])
    assert [item["name"] for item in payload["extracted"]] == ["atta"]
    released = rows(conn, "request_queue")
    assert [(row["status"], row["released_at"] is not None) for row in released] == [
        ("released", True)
    ] * 2


def test_a_start_inside_the_window_releases_what_the_night_left_and_one_before_it_does_not(
    conn: sqlite3.Connection,
) -> None:
    queue_overnight(conn, "m1")

    at_03_00 = release_queue(conn, ist(3, 0), Window())
    still_queued = [row["status"] for row in rows(conn, "request_queue")]
    at_09_40 = release_queue(conn, ist(9, 40), Window())

    assert (at_03_00, still_queued) == ([], ["queued"])
    assert len(at_09_40) == 1


def test_nothing_is_released_after_the_window_closes(conn: sqlite3.Connection) -> None:
    queue_overnight(conn, "m1")

    assert release_queue(conn, ist(22, 31), Window()) == []
    assert rows(conn, "cart_jobs") == []


def test_the_same_requests_are_never_released_twice(conn: sqlite3.Connection) -> None:
    queue_overnight(conn, "m1", "m2")

    first = release_queue(conn, ist(7, 0), Window())
    second = release_queue(conn, ist(7, 1), Window())

    assert (len(first), second) == (2, [])
    assert len(rows(conn, "cart_jobs")) == 2


def test_two_threads_releasing_at_once_still_make_one_job_per_request(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    queue_overnight(conn, "m1", "m2", "m3")
    barrier = threading.Barrier(2)
    released: list[list[int]] = []

    def release() -> None:
        with connect(db_path) as own:
            barrier.wait()
            released.append(release_queue(own, ist(7, 0), Window()))

    threads = [threading.Thread(target=release) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(len(ids) for ids in released) == [0, 3]
    assert len(rows(conn, "cart_jobs")) == 3


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (ist(3, 0), ist(7, 0)),
        (ist(6, 59), ist(7, 0)),
        (ist(7, 0), ist(7, 0, day=8)),
        (ist(22, 31), ist(7, 0, day=8)),
    ],
    ids=["03:00", "06:59", "07:00", "22:31"],
)
def test_the_next_release_is_the_next_window_start_in_the_configured_zone(
    now: datetime, expected: datetime
) -> None:
    assert next_release_time(now, Window()) == expected


def test_the_next_release_is_judged_in_the_configured_zone_whatever_zone_the_instant_is_in() -> (
    None
):
    utc = ist(3, 0).astimezone(ZoneInfo("UTC"))

    assert next_release_time(utc, Window()) == ist(7, 0)
