import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes.notify import RecordingNotify
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens
from fakes.window import Window

from chat2cart.cart.merge import CartDiff
from chat2cart.cart.outcomes import AddressNotServiceableError
from chat2cart.cart.worker import enqueue_job, run_next_job
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.db.repos import enqueue_request
from chat2cart.notify.summary import compose_summary
from chat2cart.ops.failures import (
    HEALTH_JOB_ID,
    alert_for_error,
    check_health,
    schedule_health_check,
    send_alert,
)
from chat2cart.pipeline.state import RunReport
from chat2cart.scheduling.release import build_scheduler, release_queue
from chat2cart.secrets import InMemorySecretStore
from chat2cart.swiggy.errors import DomainError, NeedsLoginError, UpstreamError
from chat2cart.understanding.schemas import ExtractedItem, ResolvedItem, SkippedItem

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "chat2cart.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def set_listener(
    conn: sqlite3.Connection, state: str, heartbeat_age: timedelta | None, now: datetime = NOW
) -> None:
    heartbeat = None if heartbeat_age is None else (now - heartbeat_age).isoformat()
    conn.execute(
        "INSERT INTO whatsapp_state (id, state, changed_at, heartbeat_at) VALUES (1, ?, ?, ?)",
        (state, now.isoformat(), heartbeat),
    )
    conn.commit()


def alert_keys(conn: sqlite3.Connection) -> list[str]:
    return [row["key"] for row in conn.execute("SELECT key FROM alerts ORDER BY key")]


def job_status(conn: sqlite3.Connection) -> str:
    row: sqlite3.Row = conn.execute("SELECT status FROM cart_jobs").fetchone()
    return str(row["status"])


def fail_one_job(conn: sqlite3.Connection, error: Exception, notify: RecordingNotify) -> None:
    """Run one cart job that fails with `error`, with the alert hook the app uses."""
    enqueue_job(conn, "message", {"inbound_ids": ["m1"], "text": "atta"})

    def handler(_source: str, _payload: dict[str, object]) -> None:
        raise error

    run_next_job(conn, handler, on_failure=lambda c, e: alert_for_error(c, e, notify, NOW))


def report(**changes: object) -> RunReport:
    fields: dict[str, object] = {
        "intent": "order",
        "dry_run": False,
        "added": [],
        "skipped": [],
        "removed": [],
        "reduced": [],
        "diffs": [],
        "total": Decimal("120"),
        "below_minimum": False,
        "sources": ["m1"],
    }
    return RunReport.model_validate({**fields, **changes})


# --- plan section 9.2, one test per row -------------------------------------------------------


def test_row_swiggy_token_expired_is_refreshed_automatically_with_no_alert() -> None:
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=30)
    endpoint = FakeTokenEndpoint()

    token = manager_for(store, endpoint).ensure_fresh()

    assert (token, len(endpoint.requests)) == ("access-2", 1)


def test_row_swiggy_session_ended_alerts_to_log_in_and_the_request_stays_queued(
    conn: sqlite3.Connection,
) -> None:
    set_listener(conn, "connected", timedelta(seconds=30))
    notify = RecordingNotify()

    fail_one_job(conn, NeedsLoginError("Run chat2cart login swiggy"), notify)
    check_health(conn, NOW, notify)

    assert alert_keys(conn) == ["swiggy.needs_login"]
    assert any("chat2cart login swiggy" in body for _, _, body in notify.sent)
    assert job_status(conn) == "pending"


def test_row_whatsapp_logged_out_alerts_through_the_notification_channel(
    conn: sqlite3.Connection,
) -> None:
    set_listener(conn, "logged_out", timedelta(seconds=30))
    notify = RecordingNotify()

    check_health(conn, NOW, notify)

    assert alert_keys(conn) == ["whatsapp.logged_out"]
    assert "chat2cart-wa login" in notify.sent[0][2]


def test_row_address_not_serviceable_alerts_and_the_failed_job_is_not_requeued_as_a_job(
    conn: sqlite3.Connection,
) -> None:
    set_listener(conn, "connected", timedelta(seconds=30))
    notify = RecordingNotify()

    fail_one_job(conn, AddressNotServiceableError("address_not_serviceable"), notify)
    check_health(conn, NOW, notify)

    assert alert_keys(conn) == ["swiggy.not_serviceable"]
    assert job_status(conn) == "failed"


def test_row_out_of_stock_or_not_found_is_listed_in_the_summary() -> None:
    text = compose_summary(
        report(
            skipped=[
                SkippedItem(name="eggs", reason="out_of_stock"),
                SkippedItem(name="dragonfruit", reason="no_match"),
            ]
        )
    )

    assert "Skipped: eggs (out_of_stock), dragonfruit (no_match)" in text


def test_row_swiggy_timeout_alerts_after_the_retries_and_the_request_stays_queued(
    conn: sqlite3.Connection,
) -> None:
    set_listener(conn, "connected", timedelta(seconds=30))
    notify = RecordingNotify()

    fail_one_job(conn, UpstreamError("Swiggy timed out"), notify)
    check_health(conn, NOW, notify)

    assert alert_keys(conn) == ["swiggy.upstream"]
    assert job_status(conn) == "pending"


def test_row_language_model_unavailable_puts_the_message_back_to_pending_with_no_alert(
    conn: sqlite3.Connection,
) -> None:
    set_listener(conn, "connected", timedelta(seconds=30))
    conn.execute(
        "INSERT INTO inbound_messages (id, chat_jid, sender_jid, sender_pn, text, received_at,"
        " status, error) VALUES ('m1', 'c', 's', '919876543210', 'atta', ?, 'failed',"
        " 'LLMTimeoutError')",
        (NOW.isoformat(),),
    )
    conn.commit()
    notify = RecordingNotify()

    check_health(conn, NOW, notify)

    status = conn.execute("SELECT status FROM inbound_messages").fetchone()["status"]
    assert (status, notify.sent) == ("pending", [])


def test_row_app_stopped_queued_requests_resume_on_restart_inside_the_window(
    conn: sqlite3.Connection,
) -> None:
    enqueue_request(conn, "m1", [ExtractedItem(name="atta")], clock=lambda: NOW)
    start_in_window = datetime(2026, 11, 7, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))

    released = release_queue(conn, start_in_window, Window())

    assert len(released) == 1


def test_row_cart_read_back_mismatch_is_reported_in_the_summary() -> None:
    item = ResolvedItem(
        name="atta", spin_id="S1", sku_id="K1", variant_name="Aashirvaad Atta 1 kg", quantity=2
    )
    diffs = [CartDiff("S1", intended=2, actual=1), CartDiff("S9", intended=None, actual=3)]

    text = compose_summary(report(added=[item], diffs=diffs))

    assert "Mismatch: Aashirvaad Atta 1 kg 2->1, S9 none->3" in text
    assert "Mismatch" not in compose_summary(report())


# --- the rest of the story's acceptance criteria -----------------------------------------------


@pytest.mark.parametrize(
    ("age_minutes", "alerted"), [(9, False), (10, False), (11, True), (60, True)]
)
def test_a_stale_heartbeat_alerts_after_10_minutes_and_not_before(
    age_minutes: int, alerted: bool, conn: sqlite3.Connection
) -> None:
    set_listener(conn, "connected", timedelta(minutes=age_minutes))

    check_health(conn, NOW, RecordingNotify())

    assert (alert_keys(conn) == ["listener.stopped"]) is alerted


def test_a_listener_that_never_reported_or_has_no_row_alerts_that_it_stopped(
    conn: sqlite3.Connection,
) -> None:
    no_row = RecordingNotify()
    check_health(conn, NOW, no_row)
    conn.execute("DELETE FROM alerts")
    set_listener(conn, "connected", None)
    null_heartbeat = RecordingNotify()

    check_health(conn, NOW, null_heartbeat)

    assert (len(no_row.sent), len(null_heartbeat.sent)) == (1, 1)


def test_the_same_alert_is_sent_once_an_hour_then_again_after_61_minutes(
    conn: sqlite3.Connection,
) -> None:
    notify = RecordingNotify()

    first = send_alert(conn, "k", "Title", "Body", notify, NOW)
    within_the_hour = send_alert(conn, "k", "Title", "Body", notify, NOW + timedelta(minutes=59))
    after_61 = send_alert(conn, "k", "Title", "Body", notify, NOW + timedelta(minutes=61))

    assert (first, within_the_hour, after_61) == (True, False, True)
    assert len(notify.sent) == 2


def test_different_alerts_do_not_hold_each_other_back(conn: sqlite3.Connection) -> None:
    notify = RecordingNotify()

    results = [send_alert(conn, key, "T", "B", notify, NOW) for key in ("a", "b")]

    assert results == [True, True]


def test_a_failed_send_is_not_counted_so_it_is_tried_again(conn: sqlite3.Connection) -> None:
    failing = RecordingNotify(result=False)
    working = RecordingNotify()

    first = send_alert(conn, "k", "T", "B", failing, NOW)
    second = send_alert(conn, "k", "T", "B", working, NOW + timedelta(minutes=5))

    assert (first, second, alert_keys(conn)) == (False, True, ["k"])


def test_alerts_go_through_notify_only_and_write_nothing_to_the_inbox(
    conn: sqlite3.Connection,
) -> None:
    notify = RecordingNotify()

    alert_for_error(conn, NeedsLoginError("login"), notify, NOW)

    assert [kind for kind, _, _ in notify.sent] == ["alert"]
    assert conn.execute("SELECT COUNT(*) FROM inbound_messages").fetchone()[0] == 0


def test_an_error_with_no_alert_of_its_own_sends_nothing(conn: sqlite3.Connection) -> None:
    notify = RecordingNotify()

    alert_for_error(conn, DomainError("CART_LOCKED", "Cart is locked", {}), notify, NOW)

    assert notify.sent == []


def test_failed_work_is_requeued_and_finished_work_is_left_alone(conn: sqlite3.Connection) -> None:
    set_listener(conn, "connected", timedelta(seconds=30))
    conn.execute(
        "INSERT INTO cart_jobs (source, payload_json, status, created_at, error)"
        " VALUES ('message', '{}', 'failed', ?, 'ValueError: boom'),"
        " ('message', '{}', 'done', ?, NULL)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()

    check_health(conn, NOW, RecordingNotify())

    statuses = [row["status"] for row in conn.execute("SELECT status FROM cart_jobs ORDER BY id")]
    assert statuses == ["pending", "done"]


def test_a_hook_that_fails_does_not_stop_the_worker(conn: sqlite3.Connection) -> None:
    enqueue_job(conn, "message", {})

    def handler(_source: str, _payload: dict[str, object]) -> None:
        raise ValueError("boom")

    def broken_hook(_conn: sqlite3.Connection, _error: Exception) -> None:
        raise RuntimeError("alert failed")

    assert run_next_job(conn, handler, on_failure=broken_hook) is True
    assert job_status(conn) == "failed"


def test_the_health_check_is_scheduled_every_five_minutes() -> None:
    scheduler = build_scheduler(Window(), lambda: None)

    schedule_health_check(scheduler, lambda: None)

    job = scheduler.get_job(HEALTH_JOB_ID)
    assert job is not None
    assert job.trigger.interval == timedelta(minutes=5)
    assert (job.coalesce, job.max_instances) == (True, 1)
