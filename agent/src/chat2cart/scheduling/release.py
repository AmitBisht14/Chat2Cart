import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from chat2cart.scheduling.window import OrderingWindow, is_within_window

RELEASE_JOB_ID = "release-queue"
RELEASE_QUEUED = """
    UPDATE request_queue SET status = 'released', released_at = ?
    WHERE status = 'queued' RETURNING id, inbound_id, items_json"""
INSERT_JOB = (
    "INSERT INTO cart_jobs (source, payload_json, status, created_at)"
    " VALUES ('queue', ?, 'pending', ?)"
)


def release_queue(conn: sqlite3.Connection, now: datetime, window: OrderingWindow) -> list[int]:
    """Turn every queued request into a cart job. Does nothing outside the ordering window.

    One transaction marks the rows released and creates their jobs, so the same request can never
    be released twice, even by two threads or two starts at once. Returns the new job ids.
    """
    if not is_within_window(now, window):
        return []
    stamp = now.isoformat()
    conn.execute("BEGIN IMMEDIATE")
    try:
        released = conn.execute(RELEASE_QUEUED, (stamp,)).fetchall()
        job_ids = [_insert_job(conn, row, stamp) for row in released]
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    if job_ids:
        structlog.get_logger().info("queue_released", requests=len(job_ids))
    return job_ids


def next_release_time(now: datetime, window: OrderingWindow) -> datetime:
    """The next time the queue is released: the next window start, in the configured zone."""
    local = now.astimezone(ZoneInfo(window.timezone))
    start = local.replace(
        hour=window.window_start.hour,
        minute=window.window_start.minute,
        second=0,
        microsecond=0,
    )
    return start if local < start else start + timedelta(days=1)


def release_trigger(window: OrderingWindow) -> CronTrigger:
    return CronTrigger(
        hour=window.window_start.hour,
        minute=window.window_start.minute,
        timezone=ZoneInfo(window.timezone),
    )


def build_scheduler(window: OrderingWindow, release: Callable[[], object]) -> BackgroundScheduler:
    """A scheduler that calls `release` at the window start.

    coalesce and no misfire limit mean a wake from sleep still fires once; the window check in
    release_queue stops a run that is too late from releasing outside the window.
    """
    scheduler = BackgroundScheduler(timezone=ZoneInfo(window.timezone))
    scheduler.add_job(
        release,
        release_trigger(window),
        id=RELEASE_JOB_ID,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=None,
    )
    return scheduler


def _insert_job(conn: sqlite3.Connection, row: sqlite3.Row, created_at: str) -> int:
    payload = {
        "inbound_ids": [row["inbound_id"]],
        "queue_ids": [row["id"]],
        "extracted": json.loads(row["items_json"]),
    }
    cursor = conn.execute(INSERT_JOB, (json.dumps(payload), created_at))
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("The cart job was not stored.")
    return cursor.lastrowid
