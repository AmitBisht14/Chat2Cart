import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from chat2cart.cart.worker import enqueue_job
from chat2cart.db.repos import enqueue_request
from chat2cart.inbox import InboxMessage
from chat2cart.llm.adapter import StructuredLLM
from chat2cart.scheduling.window import OrderingWindow, is_within_window
from chat2cart.understanding.classify import classify_message
from chat2cart.understanding.extract import extract_items

MessageHandler = Callable[[sqlite3.Connection, InboxMessage], None]


def message_handler(
    window: OrderingWindow,
    get_llm: Callable[[], StructuredLLM],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MessageHandler:
    """Decide what happens to each accepted message, by the time it arrives.

    Inside the ordering window it becomes a cart job for the pipeline. Outside the window it is
    only classified and its items extracted, then saved in the request queue for the morning. That
    path never touches Swiggy: it has no Swiggy client.
    """

    def handle(conn: sqlite3.Connection, message: InboxMessage) -> None:
        if is_within_window(clock(), window):
            enqueue_message_job(conn, message)
        else:
            asyncio.run(_queue_for_morning(conn, message, get_llm()))

    return handle


def enqueue_message_job(conn: sqlite3.Connection, message: InboxMessage) -> None:
    """A message that arrives in the window becomes one cart job; the worker runs the pipeline."""
    enqueue_job(conn, "message", {"inbound_ids": [message.id], "text": message.text})


async def _queue_for_morning(
    conn: sqlite3.Connection, message: InboxMessage, llm: StructuredLLM
) -> None:
    intent = await classify_message(message.text, llm)
    if intent.order_text is None:
        return
    items = await extract_items(intent.order_text, llm)
    if not items:
        return
    sourced = [item.model_copy(update={"sources": [message.id]}) for item in items]
    enqueue_request(conn, message.id, sourced)
    structlog.get_logger().info("queue.enqueued", inbound_id=message.id, items=len(sourced))
