import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import datetime

import structlog
from pydantic import BaseModel

from chat2cart.config import load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.logging import configure_logging
from chat2cart.swiggy.oauth import utc_now

POLL_INTERVAL_SECONDS = 1.0

RESET_STUCK = "UPDATE inbound_messages SET status = 'pending' WHERE status = 'processing'"
CLAIM_NEXT = """
    UPDATE inbound_messages SET status = 'processing', claimed_at = ?, run_id = ?
    WHERE id = (
        SELECT id FROM inbound_messages WHERE status = 'pending'
        ORDER BY received_at, rowid LIMIT 1
    )
    RETURNING *"""
FINISH = "UPDATE inbound_messages SET status = ?, finished_at = ?, error = ? WHERE id = ?"


class InboxMessage(BaseModel):
    id: str
    chat_jid: str
    sender_jid: str
    sender_pn: str | None
    text: str
    received_at: str
    status: str
    run_id: str | None


class InboxConsumer:
    """Claims accepted WhatsApp messages from the shared database and hands each to a handler.

    A claim is one atomic UPDATE, so a message is handled once. Rows left in `processing` by a
    crash are made `pending` again by start().
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        handler: Callable[[InboxMessage], None],
        clock: Callable[[], datetime] = utc_now,
        new_run_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._conn = conn
        self._handler = handler
        self._clock = clock
        self._new_run_id = new_run_id

    def start(self) -> None:
        self._conn.execute(RESET_STUCK)
        self._conn.commit()

    def process_next(self) -> bool:
        """Handle the oldest pending message. Returns False when the inbox is empty."""
        message = self._claim_next()
        if message is None:
            return False
        self._handle(message)
        return True

    def drain(self) -> int:
        handled = 0
        while self.process_next():
            handled += 1
        return handled

    def run(
        self,
        should_stop: Callable[[], bool],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.start()
        while not should_stop():
            self.drain()
            sleep(POLL_INTERVAL_SECONDS)

    def _claim_next(self) -> InboxMessage | None:
        row = self._conn.execute(CLAIM_NEXT, (self._now(), self._new_run_id())).fetchone()
        self._conn.commit()
        return None if row is None else InboxMessage.model_validate(dict(row))

    def _handle(self, message: InboxMessage) -> None:
        log = structlog.get_logger().bind(message_id=message.id)
        try:
            self._handler(message)
        except Exception as error:
            # Handler code is arbitrary: any failure is recorded on the row, not raised.
            reason = f"{type(error).__name__}: {error}"
            log.error("inbound_failed", error_type=type(error).__name__)
            self._finish(message.id, "failed", reason)
            return
        self._finish(message.id, "done", None)

    def _finish(self, message_id: str, status: str, error: str | None) -> None:
        self._conn.execute(FINISH, (status, self._now(), error, message_id))
        self._conn.commit()

    def _now(self) -> str:
        return self._clock().isoformat()


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    with closing(connect(settings.db_path)) as conn:
        version = migrate(conn)
    structlog.get_logger().info("database_ready", schema_version=version)
