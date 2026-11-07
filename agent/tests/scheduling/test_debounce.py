import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes.fake_llm import FakeLLM
from fakes.window import Window

from chat2cart.config import load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.inbox import InboxMessage
from chat2cart.scheduling.queueing import MessageHandler, message_handler
from chat2cart.scheduling.release import (
    DEBOUNCE_JOB_ID,
    build_scheduler,
    release_queue,
    schedule_debounce_release,
)
from chat2cart.understanding.schemas import ExtractedItem, Extraction, Intent

IST = ZoneInfo("Asia/Kolkata")


def ist(hour: int, minute: int = 0, day: int = 7) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "chat2cart.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def message(message_id: str) -> InboxMessage:
    return InboxMessage(
        id=message_id,
        chat_jid="chat",
        sender_jid="sender",
        sender_pn="919876543210",
        text="2 kg atta",
        received_at="2026-11-07T04:30:00Z",
        status="processing",
        run_id="run",
    )


def order_llm(times: int = 1) -> FakeLLM:
    items = [ExtractedItem(name="atta", quantity=Decimal(2), unit="kg")]
    return FakeLLM(
        *[
            outcome
            for _ in range(times)
            for outcome in (Intent(label="order"), Extraction(items=items))
        ]
    )


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now.astimezone(UTC)


def handler_for(
    llm: FakeLLM, clock: Clock, debounce: int, scheduled: list[datetime]
) -> MessageHandler:
    return message_handler(
        Window(),
        lambda: llm,
        clock=clock,
        debounce_minutes=debounce,
        schedule_release=scheduled.append,
    )


def count(conn: sqlite3.Connection, table: str) -> int:
    row: sqlite3.Row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def test_the_default_delay_is_zero_minutes(valid_env: dict[str, str]) -> None:
    assert load_settings(env_file=None).daytime_debounce_minutes == 0


def test_the_delay_is_read_from_the_configuration(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHAT2CART_DAYTIME_DEBOUNCE_MINUTES", "3")

    assert load_settings(env_file=None).daytime_debounce_minutes == 3


def test_a_negative_delay_is_rejected_naming_the_variable(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CHAT2CART_DAYTIME_DEBOUNCE_MINUTES", "-1")

    with pytest.raises(SystemExit):
        load_settings(env_file=None)

    assert "CHAT2CART_DAYTIME_DEBOUNCE_MINUTES: " in capsys.readouterr().err


def test_a_zero_delay_is_unchanged_one_message_one_cart_job_at_once(
    conn: sqlite3.Connection,
) -> None:
    llm = FakeLLM()
    scheduled: list[datetime] = []

    handler_for(llm, Clock(ist(10, 0)), 0, scheduled)(conn, message("m1"))

    (job,) = conn.execute("SELECT * FROM cart_jobs").fetchall()
    assert (job["source"], json.loads(job["payload_json"])["inbound_ids"]) == ("message", ["m1"])
    assert (count(conn, "request_queue"), scheduled, llm.calls) == (0, [], [])


def test_messages_within_the_delay_are_grouped_into_one_job(conn: sqlite3.Connection) -> None:
    clock = Clock(ist(10, 0))
    scheduled: list[datetime] = []
    handler = handler_for(order_llm(3), clock, 3, scheduled)

    for minute, message_id in ((0, "m1"), (1, "m2"), (2, "m3")):
        clock.now = ist(10, minute)
        handler(conn, message(message_id))
    assert count(conn, "cart_jobs") == 0
    release_queue(conn, ist(10, 3), Window())

    (job,) = conn.execute("SELECT * FROM cart_jobs").fetchall()
    assert json.loads(job["payload_json"])["inbound_ids"] == ["m1", "m2", "m3"]
    assert [run_at.astimezone(IST) for run_at in scheduled] == [
        ist(10, 3),
        ist(10, 4),
        ist(10, 5),
    ]


def test_a_daytime_message_that_is_not_an_order_queues_nothing_and_sets_no_timer(
    conn: sqlite3.Connection,
) -> None:
    scheduled: list[datetime] = []
    llm = FakeLLM(Intent(label="general"))

    handler_for(llm, Clock(ist(10, 0)), 3, scheduled)(conn, message("m1"))

    assert (count(conn, "request_queue"), count(conn, "cart_jobs"), scheduled) == (0, 0, [])


def test_a_night_message_sets_no_daytime_timer(conn: sqlite3.Connection) -> None:
    scheduled: list[datetime] = []

    handler_for(order_llm(), Clock(ist(23, 15, day=6)), 3, scheduled)(conn, message("m1"))

    assert (count(conn, "request_queue"), scheduled) == (1, [])


def test_one_timer_serves_the_whole_group_and_later_messages_do_not_move_it() -> None:
    scheduler = build_scheduler(Window(), lambda: None)
    release: list[int] = []

    for minute in (3, 4, 5):
        schedule_debounce_release(scheduler, ist(10, minute), lambda: release.append(1))

    jobs = [job for job in scheduler.get_jobs() if job.id == DEBOUNCE_JOB_ID]
    assert len(jobs) == 1
    assert jobs[0].trigger.run_date == ist(10, 3)
    assert (jobs[0].coalesce, jobs[0].misfire_grace_time) == (True, None)


def test_a_timer_that_fires_after_the_window_releases_nothing_and_the_morning_takes_the_group(
    conn: sqlite3.Connection,
) -> None:
    clock = Clock(ist(22, 29))
    handler_for(order_llm(), clock, 3, [])(conn, message("m1"))

    after_close = release_queue(conn, ist(22, 32), Window())
    next_morning = release_queue(conn, ist(7, 0, day=8), Window())

    assert (after_close, len(next_morning)) == ([], 1)
