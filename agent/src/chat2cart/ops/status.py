import sqlite3
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from chat2cart.config import Settings
from chat2cart.ops.failures import is_stale, listener_state
from chat2cart.scheduling.release import next_release_time

PROBLEM = "!"
LOGIN_FIX = "Run `chat2cart login swiggy`"
STATUS_ROW_ITEMS = ("WhatsApp", "Swiggy login", "Address", "Queue", "Last run", "Next release")

StatusRow = tuple[str, str, str]


class TokenStatus(Protocol):
    """What the status needs to know about the Swiggy login: its expiry, never a token."""

    def expires_at(self) -> datetime | None: ...

    def needs_login(self) -> bool: ...


def status_rows(
    conn: sqlite3.Connection, settings: Settings, tokens: TokenStatus, now: datetime
) -> list[StatusRow]:
    """Six rows of (item, value, fix). A row with a problem has a value that starts with `!`."""
    zone = ZoneInfo(settings.timezone)
    return [
        _whatsapp_row(conn, now),
        _swiggy_row(tokens, zone),
        _address_row(settings),
        _queue_row(conn),
        _last_run_row(conn, zone),
        ("Next release", _local(next_release_time(now, settings), zone), ""),
    ]


def has_problem(rows: list[StatusRow]) -> bool:
    return any(value.startswith(PROBLEM) for _, value, _ in rows)


def _whatsapp_row(conn: sqlite3.Connection, now: datetime) -> StatusRow:
    listener = listener_state(conn)
    if listener is None:
        return (
            "WhatsApp",
            f"{PROBLEM}no report from the listener yet",
            "Run `npm run service:start`",
        )
    if listener.state == "logged_out":
        return ("WhatsApp", f"{PROBLEM}logged out", "Run `chat2cart-wa login`")
    heartbeat = _heartbeat_text(listener.heartbeat_at, now)
    if is_stale(listener, now):
        return (
            "WhatsApp",
            f"{PROBLEM}{listener.state}, {heartbeat}",
            "Run `npm run service:start`",
        )
    return ("WhatsApp", f"{listener.state}, {heartbeat}", "")


def _heartbeat_text(heartbeat_at: datetime | None, now: datetime) -> str:
    if heartbeat_at is None:
        return "no heartbeat"
    seconds = int((now - heartbeat_at).total_seconds())
    return f"heartbeat {seconds}s ago" if seconds < 120 else f"heartbeat {seconds // 60} min ago"


def _swiggy_row(tokens: TokenStatus, zone: ZoneInfo) -> StatusRow:
    expires_at = tokens.expires_at()
    if tokens.needs_login() or expires_at is None:
        return ("Swiggy login", f"{PROBLEM}not logged in", LOGIN_FIX)
    return ("Swiggy login", f"access token expires {_local(expires_at, zone)}", "")


def _address_row(settings: Settings) -> StatusRow:
    if settings.default_address_id is None:
        return ("Address", f"{PROBLEM}not chosen", "Run `chat2cart swiggy address`")
    return ("Address", settings.default_address_id, "")


def _queue_row(conn: sqlite3.Connection) -> StatusRow:
    queued = _count(conn, "SELECT COUNT(*) FROM request_queue WHERE status = 'queued'")
    pending = _count(conn, "SELECT COUNT(*) FROM cart_jobs WHERE status = 'pending'")
    return ("Queue", f"{queued} queued requests, {pending} pending cart jobs", "")


def _last_run_row(conn: sqlite3.Connection, zone: ZoneInfo) -> StatusRow:
    run = conn.execute("SELECT finished_at FROM runs ORDER BY finished_at DESC LIMIT 1").fetchone()
    failed = conn.execute(
        "SELECT finished_at FROM cart_jobs WHERE status = 'failed' AND finished_at IS NOT NULL"
        " ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    run_at = None if run is None else datetime.fromisoformat(run["finished_at"])
    failed_at = None if failed is None else datetime.fromisoformat(failed["finished_at"])
    if failed_at is not None and (run_at is None or failed_at > run_at):
        value = f"{PROBLEM}failed at {_local(failed_at, zone)}"
        return ("Last run", value, "See the agent log; failed jobs are retried every 5 minutes")
    if run_at is None:
        return ("Last run", "no runs yet", "")
    return ("Last run", f"succeeded at {_local(run_at, zone)}", "")


def _count(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    return int(row[0])


def _local(instant: datetime, zone: ZoneInfo) -> str:
    return instant.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z")
