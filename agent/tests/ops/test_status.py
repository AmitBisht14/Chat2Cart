import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens
from typer.testing import CliRunner

from chat2cart.cli import app
from chat2cart.config import load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.ops.status import STATUS_ROW_ITEMS, has_problem, status_rows
from chat2cart.secrets import InMemorySecretStore

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)  # 17:30 in India
FAKE_ACCESS_TOKEN = "access-1"
FAKE_REFRESH_TOKEN = "refresh-1"
FAKE_CLIENT_ID = "client-1"


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


@pytest.fixture
def healthy(
    db_path: Path, valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> InMemorySecretStore:
    """A running, logged-in app with an address, at a fixed time."""
    monkeypatch.setenv("CHAT2CART_DB_PATH", str(db_path))
    monkeypatch.setenv("CHAT2CART_DEFAULT_ADDRESS_ID", "addr-002")
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=3600)
    monkeypatch.setattr("chat2cart.cli.build_secret_store", lambda: store)
    monkeypatch.setattr("chat2cart.cli.utc_now", lambda: NOW)
    with connect(db_path) as setup:
        set_listener(setup, "connected", timedelta(seconds=30))
    return store


def set_listener(conn: sqlite3.Connection, state: str, age: timedelta | None) -> None:
    heartbeat = None if age is None else (NOW - age).isoformat()
    conn.execute("DELETE FROM whatsapp_state")
    conn.execute(
        "INSERT INTO whatsapp_state (id, state, changed_at, heartbeat_at) VALUES (1, ?, ?, ?)",
        (state, NOW.isoformat(), heartbeat),
    )
    conn.commit()


def run_status() -> tuple[int, str]:
    result = CliRunner().invoke(app, ["status"])
    return result.exit_code, result.output


def rows_for(
    conn: sqlite3.Connection, store: InMemorySecretStore | None = None
) -> dict[str, tuple[str, str]]:
    settings = load_settings(env_file=None)
    tokens = manager_for(store or InMemorySecretStore(), FakeTokenEndpoint())
    return {item: (value, fix) for item, value, fix in status_rows(conn, settings, tokens, NOW)}


def test_all_six_items_are_shown_and_a_healthy_app_exits_zero(healthy: InMemorySecretStore) -> None:
    code, output = run_status()

    assert code == 0
    for item in STATUS_ROW_ITEMS:
        assert item in output
    assert "!" not in output


def test_a_logged_out_whatsapp_shows_its_fix_and_exits_one(
    healthy: InMemorySecretStore, db_path: Path
) -> None:
    with connect(db_path) as conn:
        set_listener(conn, "logged_out", timedelta(seconds=30))

    code, output = run_status()

    assert code == 1
    assert "!logged out" in output
    assert "chat2cart-wa login" in output


def test_no_secret_values_are_printed(healthy: InMemorySecretStore) -> None:
    code, output = run_status()

    assert code == 0
    for secret in (FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, FAKE_CLIENT_ID):
        assert secret not in output


def test_a_stale_heartbeat_is_a_problem_with_the_service_start_fix(
    healthy: InMemorySecretStore, db_path: Path
) -> None:
    with connect(db_path) as conn:
        set_listener(conn, "connected", timedelta(minutes=11))

    code, output = run_status()

    assert code == 1
    assert "heartbeat 11 min ago" in output
    assert "npm run service:start" in output


def test_a_missing_login_is_a_problem_with_the_login_fix(
    healthy: InMemorySecretStore,
) -> None:
    healthy.delete("swiggy.tokens")

    code, output = run_status()

    assert code == 1
    assert "!not logged in" in output
    assert "chat2cart login swiggy" in output


def test_a_missing_address_is_a_problem_with_the_address_fix(
    healthy: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHAT2CART_DEFAULT_ADDRESS_ID")

    code, output = run_status()

    assert code == 1
    assert "chat2cart swiggy address" in output


def test_the_expiry_is_shown_as_a_date_in_the_configured_zone(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=3600)

    value, fix = rows_for(conn, store)["Swiggy login"]

    assert (value, fix) == ("access token expires 2026-11-06 18:30 IST", "")


def test_the_queue_row_counts_queued_requests_and_pending_cart_jobs(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    conn.execute(
        "INSERT INTO request_queue (inbound_id, items_json, queued_at) VALUES"
        " ('m1', '[]', ?), ('m2', '[]', ?)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.execute(
        "INSERT INTO cart_jobs (source, payload_json, status, created_at) VALUES"
        " ('message', '{}', 'pending', ?), ('message', '{}', 'done', ?)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()

    assert rows_for(conn)["Queue"][0] == "2 queued requests, 1 pending cart jobs"


def test_the_last_run_row_shows_the_latest_run_and_that_it_succeeded(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    conn.execute(
        "INSERT INTO runs (id, started_at, finished_at, result_json) VALUES ('r1', ?, ?, '{}')",
        ((NOW - timedelta(hours=1)).isoformat(), (NOW - timedelta(hours=1)).isoformat()),
    )
    conn.commit()

    assert rows_for(conn)["Last run"] == ("succeeded at 2026-11-07 16:30 IST", "")


def test_a_failed_job_newer_than_the_last_run_is_a_problem(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    conn.execute(
        "INSERT INTO runs (id, started_at, finished_at, result_json) VALUES ('r1', ?, ?, '{}')",
        ((NOW - timedelta(hours=2)).isoformat(), (NOW - timedelta(hours=2)).isoformat()),
    )
    conn.execute(
        "INSERT INTO cart_jobs (source, payload_json, status, created_at, finished_at)"
        " VALUES ('message', '{}', 'failed', ?, ?)",
        (NOW.isoformat(), (NOW - timedelta(hours=1)).isoformat()),
    )
    conn.commit()

    value, fix = rows_for(conn)["Last run"]

    assert value.startswith("!failed at")
    assert "agent log" in fix


def test_with_no_runs_yet_the_last_run_row_says_so_and_is_not_a_problem(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    assert rows_for(conn)["Last run"] == ("no runs yet", "")


def test_the_next_release_is_the_next_window_start_in_india(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    assert rows_for(conn)["Next release"] == ("2026-11-08 07:00 IST", "")


def test_a_listener_that_never_reported_is_a_problem(
    conn: sqlite3.Connection, valid_env: dict[str, str]
) -> None:
    value, fix = rows_for(conn)["WhatsApp"]

    assert (value.startswith("!"), "service:start" in fix) == (True, True)


def test_has_problem_is_true_only_when_a_value_starts_with_a_bang() -> None:
    assert has_problem([("A", "ok", ""), ("B", "!bad", "fix")]) is True
    assert has_problem([("A", "ok", ""), ("B", "fine", "")]) is False
