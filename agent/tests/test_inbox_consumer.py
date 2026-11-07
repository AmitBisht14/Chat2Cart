import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chat2cart.app import InboxConsumer, InboxMessage
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate

NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "chat2cart.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def add_message(
    conn: sqlite3.Connection, message_id: str, received_at: str, status: str = "pending"
) -> None:
    conn.execute(
        "INSERT INTO inbound_messages"
        " (id, chat_jid, sender_jid, sender_pn, text, received_at, status)"
        " VALUES (?, 'chat', 'sender', '919876543210', 'milk', ?, ?)",
        (message_id, received_at, status),
    )
    conn.commit()


def consumer(
    conn: sqlite3.Connection, handled: list[str], failing: set[str] | None = None
) -> InboxConsumer:
    def handler(message: InboxMessage) -> None:
        handled.append(message.id)
        if message.id in (failing or set()):
            raise ValueError("cannot read this message")

    return InboxConsumer(conn, handler, clock=lambda: NOW, new_run_id=lambda: "run-1")


def status_of(conn: sqlite3.Connection, message_id: str) -> sqlite3.Row:
    row: sqlite3.Row = conn.execute(
        "SELECT status, error, claimed_at, finished_at, run_id FROM inbound_messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return row


def test_messages_received_while_the_agent_was_stopped_are_handled_oldest_first(
    conn: sqlite3.Connection,
) -> None:
    add_message(conn, "newer", "2026-11-07T09:00:02Z")
    add_message(conn, "oldest", "2026-11-07T09:00:00Z")
    add_message(conn, "middle", "2026-11-07T09:00:01Z")
    handled: list[str] = []

    inbox = consumer(conn, handled)
    inbox.start()
    inbox.drain()

    assert handled == ["oldest", "middle", "newer"]


def test_a_handled_message_ends_done_with_its_times_and_run(conn: sqlite3.Connection) -> None:
    add_message(conn, "m1", "2026-11-07T09:00:00Z")

    inbox = consumer(conn, [])
    inbox.drain()

    row = status_of(conn, "m1")
    assert (row["status"], row["error"], row["run_id"]) == ("done", None, "run-1")
    assert (row["claimed_at"], row["finished_at"]) == (NOW.isoformat(), NOW.isoformat())


def test_a_handler_exception_ends_failed_with_a_reason_and_others_still_complete(
    conn: sqlite3.Connection,
) -> None:
    add_message(conn, "bad", "2026-11-07T09:00:00Z")
    add_message(conn, "good", "2026-11-07T09:00:01Z")

    consumer(conn, [], failing={"bad"}).drain()

    assert status_of(conn, "bad")["status"] == "failed"
    assert status_of(conn, "bad")["error"] == "ValueError: cannot read this message"
    assert status_of(conn, "good")["status"] == "done"


def test_a_message_left_processing_by_a_crash_is_handled_again_after_restart(
    conn: sqlite3.Connection,
) -> None:
    add_message(conn, "stuck", "2026-11-07T09:00:00Z", status="processing")
    handled: list[str] = []

    inbox = consumer(conn, handled)
    inbox.start()
    inbox.drain()

    assert handled == ["stuck"]
    assert status_of(conn, "stuck")["status"] == "done"


def test_done_and_failed_messages_are_not_handled_again_after_restart(
    conn: sqlite3.Connection,
) -> None:
    add_message(conn, "old-done", "2026-11-07T09:00:00Z", status="done")
    add_message(conn, "old-failed", "2026-11-07T09:00:01Z", status="failed")
    handled: list[str] = []

    inbox = consumer(conn, handled)
    inbox.start()
    inbox.drain()

    assert handled == []


def test_an_empty_inbox_reports_nothing_to_handle(conn: sqlite3.Connection) -> None:
    assert consumer(conn, []).process_next() is False


def test_run_polls_until_told_to_stop_and_sleeps_between_polls(conn: sqlite3.Connection) -> None:
    add_message(conn, "m1", "2026-11-07T09:00:00Z")
    handled: list[str] = []
    sleeps: list[float] = []
    stop_after_two_polls = iter([False, False, True])

    consumer(conn, handled).run(lambda: next(stop_after_two_polls), sleep=sleeps.append)

    assert handled == ["m1"]
    assert sleeps == [1.0, 1.0]
