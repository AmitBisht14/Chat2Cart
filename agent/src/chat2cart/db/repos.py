import json
import sqlite3
from collections.abc import Callable
from datetime import datetime

from chat2cart.swiggy.oauth import utc_now
from chat2cart.understanding.schemas import ExtractedItem

INSERT_REQUEST = (
    "INSERT INTO request_queue (inbound_id, items_json, queued_at, status)"
    " VALUES (?, ?, ?, 'queued')"
)


def enqueue_request(
    conn: sqlite3.Connection,
    inbound_id: str,
    items: list[ExtractedItem],
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Put a request back in the queue as `queued`, with the items already extracted from it."""
    items_json = json.dumps([item.model_dump(mode="json") for item in items])
    cursor = conn.execute(INSERT_REQUEST, (inbound_id, items_json, clock().isoformat()))
    conn.commit()
    if cursor.lastrowid is None:
        raise sqlite3.DatabaseError("The request was not queued.")
    return cursor.lastrowid
