import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.fake_llm import FakeLLM
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.cart.outcomes import (
    AddressNotServiceableError,
    CappedItem,
    capped_items,
    is_below_minimum,
    is_not_serviceable,
)
from chat2cart.cart.worker import JobHandler, enqueue_job, run_next_job
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.pipeline.graph import PipelineStopped, run_pipeline
from chat2cart.pipeline.handler import pipeline_job_handler
from chat2cart.pipeline.state import PipelineDeps, RunReport
from chat2cart.swiggy.cart import ReducedItem
from chat2cart.swiggy.errors import DomainError
from chat2cart.understanding.rulebook import parse_rulebook
from chat2cart.understanding.schemas import ExtractedItem, Extraction, Intent

ADDRESS_ID = "addr-002"
RULEBOOK = parse_rulebook("## Atta\n- brand: Aashirvaad\n- size: 1 kg\n- default_quantity: 1\n")
EMPTY_CART: dict[str, object] = {"items": [], "cartTotalAmount": "0", "cartAbsent": True}
NOT_SERVICEABLE: dict[str, object] = {
    "success": False,
    "code": "ADDRESS_NOT_SERVICEABLE",
    "message": "Address not serviceable",
}


def cart_total(total: str) -> dict[str, object]:
    return {
        "items": [{"spinId": "ATTA-AS-1", "skuId": "SKU-AS-1", "itemName": "Atta", "quantity": 2}],
        "cartTotalAmount": total,
        "cartAbsent": False,
    }


def order_llm() -> FakeLLM:
    items = [ExtractedItem(name="atta", quantity=Decimal(2), unit="kg")]
    return FakeLLM(Intent(label="order"), Extraction(items=items))


def deps_for(transport: FakeSwiggyTransport) -> PipelineDeps:
    return PipelineDeps(
        llm=order_llm(),
        swiggy=logged_in_client(transport),
        load_rulebook=lambda: RULEBOOK,
        address_id=ADDRESS_ID,
    )


def order_transport(update: dict[str, object], after: dict[str, object]) -> FakeSwiggyTransport:
    return FakeSwiggyTransport(
        {"items": []},
        {"orders": []},
        load_swiggy_fixture("search_products_atta"),
        EMPTY_CART,
        update,
        after,
    )


def run_order(transport: FakeSwiggyTransport) -> RunReport:
    payload: dict[str, object] = {"inbound_ids": ["m1"], "text": "2 kg atta"}
    return asyncio.run(run_pipeline(payload, deps_for(transport)))["report"]


def calls_named(transport: FakeSwiggyTransport, name: str) -> int:
    return len([call for call in transport.calls if call.name == name])


@pytest.mark.parametrize(
    ("total", "expected"),
    [("98", True), ("98.99", True), ("99", False), ("250", False)],
)
def test_a_cart_total_under_99_rupees_is_below_the_minimum(total: str, expected: bool) -> None:
    assert is_below_minimum(Decimal(total)) is expected


def test_an_unknown_total_is_not_below_the_minimum() -> None:
    assert is_below_minimum(None) is False


def test_cart_under_minimum_is_still_written_and_flagged() -> None:
    transport = order_transport(load_swiggy_fixture("update_cart_ok"), cart_total("98"))

    report = run_order(transport)

    assert calls_named(transport, "update_cart") == 1
    assert (report.below_minimum, report.total) == (True, Decimal("98"))


def test_a_cart_at_or_over_the_minimum_is_not_flagged() -> None:
    transport = order_transport(load_swiggy_fixture("update_cart_ok"), cart_total("120"))

    report = run_order(transport)

    assert report.below_minimum is False


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        ("ADDRESS_NOT_SERVICEABLE", "anything", True),
        ("NOT_SERVICEABLE", "anything", True),
        (None, "Sorry, this address is not serviceable right now", True),
        ("OUT_OF_STOCK", "Item unavailable", False),
        (None, "Something went wrong", False),
    ],
)
def test_a_not_serviceable_error_is_told_apart_by_code_then_by_message(
    code: str | None, message: str, expected: bool
) -> None:
    assert is_not_serviceable(DomainError(code, message, {})) is expected


def test_out_of_stock_and_capped_reasons_are_in_the_report() -> None:
    removed = load_swiggy_fixture("update_cart_removed_oos")
    removed["reducedQuantityItems"] = load_swiggy_fixture("update_cart_reduced_qty")[
        "reducedQuantityItems"
    ]
    transport = order_transport(removed, cart_total("120"))

    report = run_order(transport)

    assert [(s.name, s.reason) for s in report.skipped] == [
        ("Example Dairy Toned Milk 2 l", "out_of_stock")
    ]
    assert report.reduced == [
        CappedItem(name="Sample Farms Full Cream Milk 500 ml", requested=99, applied=20)
    ]


def test_capped_items_carry_the_requested_and_applied_quantities_and_the_reason_capped() -> None:
    reduced = ReducedItem.model_validate(
        {"spinId": "S1", "itemName": "Atta", "requestedQuantity": 30, "cappedQuantity": 20}
    )

    (item,) = capped_items([reduced], [])

    assert (item.reason, item.requested, item.applied) == ("capped", 30, 20)


def test_a_business_error_is_not_retried() -> None:
    transport = FakeSwiggyTransport(
        {"items": []},
        {"orders": []},
        load_swiggy_fixture("search_products_atta"),
        EMPTY_CART,
        {"success": False, "code": "CART_LOCKED", "message": "Cart is locked"},
    )

    with pytest.raises(PipelineStopped):
        run_order(transport)

    assert calls_named(transport, "update_cart") == 1


def test_not_serviceable_stops_before_any_cart_write() -> None:
    transport = FakeSwiggyTransport({"items": []}, {"orders": []}, NOT_SERVICEABLE)

    with pytest.raises(PipelineStopped) as stopped:
        run_order(transport)

    assert calls_named(transport, "update_cart") == 0
    assert calls_named(transport, "search_products") == 1
    assert [item.name for item in stopped.value.state["extracted"]] == ["atta"]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "chat2cart.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def job_handler(db_path: Path, transport: FakeSwiggyTransport) -> JobHandler:
    @contextmanager
    def open_deps() -> Iterator[PipelineDeps]:
        yield deps_for(transport)

    return pipeline_job_handler(db_path, open_deps)


def test_not_serviceable_stops_requeues_and_fails_the_job(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    transport = FakeSwiggyTransport({"items": []}, {"orders": []}, NOT_SERVICEABLE)
    enqueue_job(conn, "message", {"inbound_ids": ["m1"], "text": "2 kg atta"})

    run_next_job(conn, job_handler(tmp_path / "chat2cart.sqlite", transport))

    job = conn.execute("SELECT status, error FROM cart_jobs").fetchone()
    assert job["status"] == "failed"
    assert "address_not_serviceable" in job["error"]
    assert calls_named(transport, "update_cart") == 0
    (queued,) = conn.execute("SELECT * FROM request_queue").fetchall()
    assert (queued["inbound_id"], queued["status"]) == ("m1", "queued")
    assert [item["name"] for item in json.loads(queued["items_json"])] == ["atta"]
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_another_business_error_fails_the_job_without_requeueing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    other = {"success": False, "code": "CART_LOCKED", "message": "Cart is locked"}
    transport = FakeSwiggyTransport({"items": []}, {"orders": []}, other)
    enqueue_job(conn, "message", {"inbound_ids": ["m1"], "text": "2 kg atta"})

    run_next_job(conn, job_handler(tmp_path / "chat2cart.sqlite", transport))

    job = conn.execute("SELECT status, error FROM cart_jobs").fetchone()
    assert job["status"] == "failed"
    assert "Cart is locked" in job["error"]
    assert conn.execute("SELECT COUNT(*) FROM request_queue").fetchone()[0] == 0


def test_the_not_serviceable_error_is_a_swiggy_error_with_the_reason_as_its_message() -> None:
    assert str(AddressNotServiceableError("address_not_serviceable")) == "address_not_serviceable"
