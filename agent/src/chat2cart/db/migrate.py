import re
import sqlite3
from importlib.resources import files

MIGRATION_NAME = re.compile(r"(\d{3})_.+\.sql")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the stored schema version and return the new version."""
    current = _current_version(conn)
    for number, sql in _pending_migrations(current):
        _apply(conn, number, sql)
        current = number
    return current


def _current_version(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
    ).fetchone()
    if has_table is None:
        return 0
    row = conn.execute("SELECT version FROM schema_meta").fetchone()
    return int(row["version"]) if row else 0


def _pending_migrations(current: int) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for file in files("chat2cart.db.migrations").iterdir():
        match = MIGRATION_NAME.fullmatch(file.name)
        if match and int(match.group(1)) > current:
            found.append((int(match.group(1)), file.read_text(encoding="utf-8")))
    return sorted(found)


def _apply(conn: sqlite3.Connection, number: int, sql: str) -> None:
    # executescript commits first, so each file carries its own BEGIN and COMMIT.
    script = (
        f"BEGIN;\n{sql}\n"
        f"DELETE FROM schema_meta;\nINSERT INTO schema_meta (version) VALUES ({number});\nCOMMIT;"
    )
    try:
        conn.executescript(script)
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
