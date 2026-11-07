import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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
    debounce_minutes: int = 0,
    schedule_release: Callable[[datetime], None] = lambda _run_at: None,
) -> MessageHandler:
    """Decide what happens to each accepted message, by the time it arrives.

    Inside the ordering window, with no delay, it becomes a cart job for the pipeline. With a
    delay (debounce_minutes), or outside the window, it is only classified and its items extracted,
    then saved in the request queue. At night the 07:00 release takes the queue; in the day
    schedule_release is asked to release it when the delay ends, so quick messages become one job.
    This path never touches Swiggy: it has no Swiggy client.
    """

    def handle(conn: sqlite3.Connection, message: InboxMessage) -> None:
        now = clock()
        in_window = is_within_window(now, window)
        if in_window and debounce_minutes == 0:
            enqueue_message_job(conn, message)
            return
        queued = asyncio.run(_queue_request(conn, message, get_llm()))
        if queued and in_window:
            schedule_release(now + timedelta(minutes=debounce_minutes))

    return handle


def enqueue_message_job(conn: sqlite3.Connection, message: InboxMessage) -> None:
    """A message that arrives in the window becomes one cart job; the worker runs the pipeline."""
    enqueue_job(conn, "message", {"inbound_ids": [message.id], "text": message.text})


async def _queue_request(
    conn: sqlite3.Connection, message: InboxMessage, llm: StructuredLLM
) -> bool:
    """Understand a message and save its items in the request queue. True if anything was queued."""
    intent = await classify_message(message.text, llm)
    if intent.order_text is None:
        return False
    items = await extract_items(intent.order_text, llm)
    if not items:
        return False
    sourced = [item.model_copy(update={"sources": [message.id]}) for item in items]
    enqueue_request(conn, message.id, sourced)
    structlog.get_logger().info("queue.enqueued", inbound_id=message.id, items=len(sourced))
    return True
