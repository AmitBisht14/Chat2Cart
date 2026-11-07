from pathlib import Path

import pytest

from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate

EXPECTED_TABLES = {
    "schema_meta",
    "inbound_messages",
    "whatsapp_state",
    "lid_map",
    "request_queue",
    "cart_jobs",
    "runs",
    "alerts",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "chat2cart.sqlite"


def test_creates_the_database_in_wal_mode(db_path: Path) -> None:
    conn = connect(db_path)

    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert (mode, db_path.exists()) == ("wal", True)


def test_creates_every_table_and_reports_version_1(db_path: Path) -> None:
    conn = connect(db_path)

    version = migrate(conn)

    names = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert (version, EXPECTED_TABLES <= names) == (1, True)


def test_second_migrate_changes_nothing(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)
    conn.execute("INSERT INTO alerts (key, last_sent_at) VALUES ('k', '2026-01-01T00:00:00Z')")
    conn.commit()

    version = migrate(conn)

    rows = conn.execute("SELECT version FROM schema_meta").fetchall()
    alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert (version, len(rows), alerts) == (1, 1, 1)


def test_rejects_an_unknown_message_status(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)

    with pytest.raises(Exception, match="CHECK constraint failed"):
        conn.execute(
            "INSERT INTO inbound_messages (id, chat_jid, sender_jid, text, received_at, status)"
            " VALUES ('m1', 'c', 's', 't', '2026-01-01T00:00:00Z', 'bogus')"
        )
