import asyncio
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes.fake_llm import FakeLLM
from fakes.notify import RecordingNotify
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client
from fakes.window import Window

from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.db.repos import enqueue_request
from chat2cart.pipeline.graph import run_pipeline
from chat2cart.pipeline.state import PipelineDeps
from chat2cart.scheduling.release import release_queue
from chat2cart.understanding.rulebook import parse_rulebook
from chat2cart.understanding.schemas import ExtractedItem

IST = ZoneInfo("Asia/Kolkata")
RULEBOOK = parse_rulebook(
    "## Milk\n- brand: Example Dairy\n- size: 500 ml\n- default_quantity: 1\n"
)
EMPTY_CART: dict[str, object] = {"items": [], "cartTotalAmount": "0", "cartAbsent": True}
CART_AFTER: dict[str, object] = {
    "items": [
        {"spinId": "0A1B2C3D", "skuId": "000123456", "itemName": "Toned Milk", "quantity": 1}
    ],
    "cartTotalAmount": "29",
    "cartAbsent": False,
}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "chat2cart.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def at(hour: int, minute: int = 0, day: int = 6) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def queue(conn: sqlite3.Connection, inbound_id: str, name: str, minute: int) -> None:
    item = ExtractedItem(name=name, quantity=None if name != "dragonfruit" else Decimal(1))
    enqueue_request(conn, inbound_id, [item], clock=lambda: at(23, minute))


def release(conn: sqlite3.Connection) -> dict[str, object]:
    (job_id,) = release_queue(conn, at(7, 0, day=7), Window())
    row = conn.execute("SELECT payload_json FROM cart_jobs WHERE id = ?", (job_id,)).fetchone()
    payload: dict[str, object] = json.loads(row["payload_json"])
    return payload


def deps_for(transport: FakeSwiggyTransport) -> PipelineDeps:
    return PipelineDeps(
        llm=FakeLLM(),
        swiggy=logged_in_client(transport),
        load_rulebook=lambda: RULEBOOK,
        address_id="addr-002",
        notify=RecordingNotify(),
    )


def milk_transport(update: dict[str, object] | None = None) -> FakeSwiggyTransport:
    return FakeSwiggyTransport(
        {"items": []},
        {"orders": []},
        load_swiggy_fixture("search_products_milk"),
        EMPTY_CART,
        update or load_swiggy_fixture("update_cart_ok"),
        CART_AFTER,
    )


def test_all_released_rows_form_one_job_with_every_inbound_id(conn: sqlite3.Connection) -> None:
    queue(conn, "m1", "milk", 0)
    queue(conn, "m2", "bread", 5)
    queue(conn, "m3", "eggs", 10)

    payload = release(conn)

    assert conn.execute("SELECT COUNT(*) FROM cart_jobs").fetchone()[0] == 1
    assert payload["inbound_ids"] == ["m1", "m2", "m3"]


def test_items_are_joined_in_the_order_the_requests_were_queued_each_with_its_message(
    conn: sqlite3.Connection,
) -> None:
    queue(conn, "late", "eggs", 30)
    queue(conn, "early", "milk", 0)

    payload = release(conn)

    items = payload["extracted"]
    assert isinstance(items, list)
    assert [(item["name"], item["sources"]) for item in items] == [
        ("milk", ["early"]),
        ("eggs", ["late"]),
    ]


def test_nothing_queued_makes_no_job(conn: sqlite3.Connection) -> None:
    assert release_queue(conn, at(7, 0, day=7), Window()) == []
    assert conn.execute("SELECT COUNT(*) FROM cart_jobs").fetchone()[0] == 0


def test_the_batch_is_deduped_before_the_cart_so_milk_twice_is_one_line(
    conn: sqlite3.Connection,
) -> None:
    queue(conn, "A", "milk", 0)
    queue(conn, "B", "Milk", 5)
    payload = release(conn)
    transport = milk_transport()

    state = asyncio.run(run_pipeline(payload, deps_for(transport)))

    updates = [call for call in transport.calls if call.name == "update_cart"]
    assert len(updates) == 1
    assert updates[0].arguments["items"] == [
        {"spinId": "0A1B2C3D", "skuId": "000123456", "quantity": 1}
    ]
    (added,) = state["report"].added
    assert (added.quantity, added.sources) == (1, ["A", "B"])


def test_the_report_lists_the_source_message_of_every_item(conn: sqlite3.Connection) -> None:
    queue(conn, "A", "milk", 0)
    queue(conn, "B", "dragonfruit", 5)
    payload = release(conn)

    state = asyncio.run(run_pipeline(payload, deps_for(milk_transport())))

    report = state["report"]
    assert [(item.name, item.sources) for item in report.added] == [("milk", ["A"])]
    assert [(item.name, item.reason, item.sources) for item in report.skipped] == [
        ("dragonfruit", "no_rule", ["B"])
    ]


def test_out_of_stock_and_capped_items_name_the_message_they_came_from(
    conn: sqlite3.Connection,
) -> None:
    queue(conn, "A", "milk", 0)
    payload = release(conn)
    update: dict[str, object] = {
        "removedOutOfStockItems": [
            {"spinId": "0A1B2C3D", "skuId": "000123456", "itemName": "Toned Milk", "quantity": 1}
        ],
        "reducedQuantityItems": [
            {
                "spinId": "0A1B2C3D",
                "itemName": "Toned Milk",
                "requestedQuantity": 99,
                "cappedQuantity": 20,
            }
        ],
    }

    state = asyncio.run(run_pipeline(payload, deps_for(milk_transport(update))))

    report = state["report"]
    assert [(item.reason, item.sources) for item in report.skipped] == [("out_of_stock", ["A"])]
    assert [(item.reason, item.sources) for item in report.reduced] == [("capped", ["A"])]
