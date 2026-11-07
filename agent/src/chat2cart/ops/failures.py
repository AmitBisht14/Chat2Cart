import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel

from chat2cart.cart.outcomes import NOT_SERVICEABLE_REASON, AddressNotServiceableError
from chat2cart.notify.base import Notify
from chat2cart.swiggy.errors import NeedsLoginError, UpstreamError

ALERT_REPEAT_AFTER = timedelta(hours=1)
LISTENER_STALE_AFTER = timedelta(minutes=10)
HEALTH_CHECK_MINUTES = 5
HEALTH_JOB_ID = "health-check"

SELECT_ALERT = "SELECT last_sent_at FROM alerts WHERE key = ?"
UPSERT_ALERT = """
    INSERT INTO alerts (key, last_sent_at) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET last_sent_at = excluded.last_sent_at"""
REQUEUE_MESSAGES = "UPDATE inbound_messages SET status = 'pending' WHERE status = 'failed'"
REQUEUE_JOBS = """
    UPDATE cart_jobs SET status = 'pending'
    WHERE status = 'failed' AND COALESCE(error, '') NOT LIKE ?"""


class ListenerState(BaseModel):
    state: str
    heartbeat_at: datetime | None


def send_alert(
    conn: sqlite3.Connection, key: str, title: str, body: str, notify: Notify, now: datetime
) -> bool:
    """Send an alert through the notification channel, at most once an hour for each key.

    Alerts never go through WhatsApp. Returns True when one was sent; a failed send is not
    counted, so it is tried again next time.
    """
    last = conn.execute(SELECT_ALERT, (key,)).fetchone()
    if last is not None and now - datetime.fromisoformat(last["last_sent_at"]) < ALERT_REPEAT_AFTER:
        return False
    if not notify("alert", title, body):
        return False
    conn.execute(UPSERT_ALERT, (key, now.isoformat()))
    conn.commit()
    return True


def alert_for_error(
    conn: sqlite3.Connection, error: Exception, notify: Notify, now: datetime
) -> None:
    """The alert for a failed cart job, by kind of error. Other errors send no alert."""
    if isinstance(error, NeedsLoginError):
        send_alert(
            conn,
            "swiggy.needs_login",
            "Swiggy login needed",
            "Swiggy needs you to log in again. Run `chat2cart login swiggy`. "
            "Your request stays queued.",
            notify,
            now,
        )
    elif isinstance(error, UpstreamError):
        send_alert(
            conn,
            "swiggy.upstream",
            "Swiggy is not answering",
            "Swiggy did not answer after several tries. Your request stays queued and is retried.",
            notify,
            now,
        )
    elif isinstance(error, AddressNotServiceableError):
        send_alert(
            conn,
            "swiggy.not_serviceable",
            "Address not serviceable",
            "Swiggy cannot deliver to your address right now. "
            "Your request stays queued and is tried again.",
            notify,
            now,
        )


def check_health(conn: sqlite3.Connection, now: datetime, notify: Notify) -> None:
    """The periodic check: alert about WhatsApp, then requeue failed work. Nothing is dropped."""
    _check_listener(conn, now, notify)
    requeue_failed(conn)


def requeue_failed(conn: sqlite3.Connection) -> None:
    """Failed messages (for example the model was down) and failed cart jobs go back to pending.

    Jobs stopped by an address that is not serviceable are left alone: their requests are already
    back in the request queue and are released later.
    """
    conn.execute(REQUEUE_MESSAGES)
    conn.execute(REQUEUE_JOBS, (f"%{NOT_SERVICEABLE_REASON}%",))
    conn.commit()


def schedule_health_check(scheduler: BackgroundScheduler, check: Callable[[], object]) -> None:
    scheduler.add_job(
        check,
        "interval",
        minutes=HEALTH_CHECK_MINUTES,
        id=HEALTH_JOB_ID,
        coalesce=True,
        max_instances=1,
    )


def _check_listener(conn: sqlite3.Connection, now: datetime, notify: Notify) -> None:
    listener = listener_state(conn)
    if listener is not None and listener.state == "logged_out":
        send_alert(
            conn,
            "whatsapp.logged_out",
            "WhatsApp logged out",
            "WhatsApp logged this device out. Run `chat2cart-wa login` to link it again.",
            notify,
            now,
        )
    elif listener is None or is_stale(listener, now):
        send_alert(
            conn,
            "listener.stopped",
            "WhatsApp listener stopped",
            "The WhatsApp listener has not reported for over 10 minutes. "
            "Messages sent now may be missed. Check that it is running.",
            notify,
            now,
        )
        structlog.get_logger().warning("listener_stale")


def listener_state(conn: sqlite3.Connection) -> ListenerState | None:
    row = conn.execute("SELECT state, heartbeat_at FROM whatsapp_state WHERE id = 1").fetchone()
    return None if row is None else ListenerState.model_validate(dict(row))


def is_stale(listener: ListenerState, now: datetime) -> bool:
    return listener.heartbeat_at is None or now - listener.heartbeat_at > LISTENER_STALE_AFTER
