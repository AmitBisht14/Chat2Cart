import ast
import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.fake_llm import FakeLLM
from fakes.window import Window

from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.inbox import InboxMessage, start_inbox_consumer
from chat2cart.llm.adapter import LLMTimeoutError
from chat2cart.scheduling import queueing
from chat2cart.scheduling.queueing import MessageHandler, message_handler
from chat2cart.understanding.schemas import ExtractedItem, Extraction, Intent

AT_23_15_IST = datetime(2026, 11, 6, 17, 45, tzinfo=UTC)
AT_10_00_IST = datetime(2026, 11, 7, 4, 30, tzinfo=UTC)
TEXT = "2 kg atta please"


def order_llm() -> FakeLLM:
    items = [ExtractedItem(name="atta", quantity=Decimal(2), unit="kg")]
    return FakeLLM(Intent(label="order"), Extraction(items=items))


def handler_for(llm: FakeLLM, now: datetime) -> MessageHandler:
    return message_handler(Window(), lambda: llm, clock=lambda: now)


def message(message_id: str = "m1", text: str = TEXT) -> InboxMessage:
    return InboxMessage(
        id=message_id,
        chat_jid="chat",
        sender_jid="sender",
        sender_pn="919876543210",
        text=text,
        received_at="2026-11-06T17:45:00Z",
        status="processing",
        run_id="run",
    )


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


def count(conn: sqlite3.Connection, table: str) -> int:
    row: sqlite3.Row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def test_out_of_window_is_stored_for_the_morning_not_sent_to_swiggy(
    conn: sqlite3.Connection,
) -> None:
    handler_for(order_llm(), AT_23_15_IST)(conn, message())

    assert count(conn, "cart_jobs") == 0
    (queued,) = conn.execute("SELECT * FROM request_queue").fetchall()
    assert (queued["inbound_id"], queued["status"]) == ("m1", "queued")
    (item,) = json.loads(queued["items_json"])
    assert (item["name"], item["quantity"], item["unit"], item["sources"]) == (
        "atta",
        "2",
        "kg",
        ["m1"],
    )


def test_the_out_of_window_path_has_no_swiggy_client() -> None:
    tree = ast.parse(Path(queueing.__file__).read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

    assert not [name for name in imports if name.startswith("chat2cart.swiggy")]


def test_the_queue_survives_a_restart_with_the_inbound_id_and_items(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    handler_for(order_llm(), AT_23_15_IST)(conn, message("m7"))
    conn.close()

    with connect(db_path) as reopened:
        (queued,) = reopened.execute("SELECT * FROM request_queue").fetchall()

    assert queued["inbound_id"] == "m7"
    assert [item["name"] for item in json.loads(queued["items_json"])] == ["atta"]


def test_in_the_window_a_cart_job_is_created_and_nothing_is_queued(
    conn: sqlite3.Connection,
) -> None:
    llm = FakeLLM()

    handler_for(llm, AT_10_00_IST)(conn, message())

    (job,) = conn.execute("SELECT * FROM cart_jobs").fetchall()
    assert (job["status"], json.loads(job["payload_json"])) == (
        "pending",
        {"inbound_ids": ["m1"], "text": TEXT},
    )
    assert count(conn, "request_queue") == 0
    assert llm.calls == []


@pytest.mark.parametrize("label", ["general", "unsure"])
def test_a_general_or_unsure_message_out_of_window_is_not_queued(
    label: str, conn: sqlite3.Connection
) -> None:
    llm = FakeLLM(Intent.model_validate({"label": label}))

    handler_for(llm, AT_23_15_IST)(conn, message())

    assert (count(conn, "request_queue"), count(conn, "cart_jobs")) == (0, 0)


def test_only_the_order_part_of_a_mixed_message_is_extracted_and_queued(
    conn: sqlite3.Connection,
) -> None:
    items = [ExtractedItem(name="milk", quantity=Decimal(2))]
    llm = FakeLLM(Intent(label="mixed", order_text="2 milk"), Extraction(items=items))

    handler_for(llm, AT_23_15_IST)(conn, message(text="hi! 2 milk, and call mom"))

    assert "2 milk" in llm.calls[1].user
    assert "call mom" not in llm.calls[1].user
    assert count(conn, "request_queue") == 1


def test_an_order_with_no_items_is_not_queued(conn: sqlite3.Connection) -> None:
    llm = FakeLLM(Intent(label="order"), Extraction(items=[]))

    handler_for(llm, AT_23_15_IST)(conn, message())

    assert count(conn, "request_queue") == 0


def test_a_model_failure_is_raised_so_the_message_is_marked_failed(
    conn: sqlite3.Connection,
) -> None:
    llm = FakeLLM(LLMTimeoutError("slow"))

    with pytest.raises(LLMTimeoutError):
        handler_for(llm, AT_23_15_IST)(conn, message())

    assert count(conn, "request_queue") == 0


def test_the_consumer_marks_a_queued_night_message_done(db_path: Path) -> None:
    with connect(db_path) as setup:
        setup.execute(
            "INSERT INTO inbound_messages (id, chat_jid, sender_jid, sender_pn, text, received_at)"
            " VALUES ('m1', 'chat', 'sender', '919876543210', ?, '2026-11-06T17:45:00Z')",
            (TEXT,),
        )
        setup.commit()
    inbox = start_inbox_consumer(db_path, handler_for(order_llm(), AT_23_15_IST))
    try:
        deadline = time.monotonic() + 5.0
        status = "pending"
        while status != "done" and time.monotonic() < deadline:
            with connect(db_path) as reader:
                status = reader.execute("SELECT status FROM inbound_messages").fetchone()["status"]
            time.sleep(0.02)
    finally:
        inbox.stop()

    with connect(db_path) as reader:
        assert status == "done"
        assert count(reader, "request_queue") == 1
