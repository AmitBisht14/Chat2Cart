import asyncio
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.fake_llm import FakeLLM
from fakes.notify import RecordingNotify
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.cart.worker import start_cart_worker
from chat2cart.config import load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.inbox import start_inbox_consumer
from chat2cart.logging import configure_logging
from chat2cart.pipeline.graph import run_pipeline
from chat2cart.pipeline.handler import pipeline_job_handler
from chat2cart.pipeline.state import OrderState, PipelineDeps
from chat2cart.scheduling.queueing import enqueue_message_job
from chat2cart.swiggy.errors import BlockedToolError
from chat2cart.understanding.rulebook import parse_rulebook
from chat2cart.understanding.schemas import ExtractedItem, Extraction, Intent

ADDRESS_ID = "addr-002"
MESSAGE_TEXT = "2 kg atta please"
RULEBOOK = parse_rulebook("## Atta\n- brand: Aashirvaad\n- size: 1 kg\n- default_quantity: 1\n")
EMPTY_CART: dict[str, object] = {"items": [], "cartTotalAmount": "0", "cartAbsent": True}
CART_AFTER: dict[str, object] = {
    "items": [
        {"spinId": "ATTA-AS-1", "skuId": "SKU-AS-1", "itemName": "Aashirvaad Atta", "quantity": 2}
    ],
    "cartTotalAmount": "120",
    "cartAbsent": False,
}
NODE_ORDER = ["classify", "extract", "apply_rulebook", "resolve", "merge_cart", "report"]


def order_llm() -> FakeLLM:
    items = [ExtractedItem(name="atta", quantity=Decimal(2), unit="kg")]
    return FakeLLM(Intent(label="order"), Extraction(items=items))


def order_transport() -> FakeSwiggyTransport:
    """The calls of one order, in order: hints, search, then read, write and read back the cart."""
    return FakeSwiggyTransport(
        {"items": []},
        {"orders": []},
        load_swiggy_fixture("search_products_atta"),
        EMPTY_CART,
        load_swiggy_fixture("update_cart_ok"),
        CART_AFTER,
    )


def deps_for(llm: FakeLLM, transport: FakeSwiggyTransport) -> PipelineDeps:
    return PipelineDeps(
        llm=llm,
        swiggy=logged_in_client(transport),
        load_rulebook=lambda: RULEBOOK,
        address_id=ADDRESS_ID,
        notify=RecordingNotify(),
    )


def run(
    deps: PipelineDeps, payload: dict[str, object] | None = None, dry_run: bool = False
) -> OrderState:
    job = payload or {"inbound_ids": ["m1"], "text": MESSAGE_TEXT}
    return asyncio.run(run_pipeline(job, deps, dry_run))


def logged_events(settings_dir: Path) -> list[dict[str, object]]:
    lines = (settings_dir / "data" / "logs" / "agent.log").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.fixture
def logs(valid_env: dict[str, str]) -> Path:
    configure_logging(load_settings(env_file=None))
    return Path(valid_env["CHAT2CART_DATA_DIR"]).parent


def step_nodes(events: list[dict[str, object]]) -> list[object]:
    return [event["node"] for event in events if event["event"] == "pipeline_step"]


def test_the_steps_run_in_the_order_of_plan_section_2_1(logs: Path) -> None:
    run(deps_for(order_llm(), order_transport()))

    assert step_nodes(logged_events(logs)) == NODE_ORDER


def test_every_step_logs_its_input_and_output_with_the_same_run_id(logs: Path) -> None:
    state = run(deps_for(order_llm(), order_transport()))

    steps = [e for e in logged_events(logs) if e["event"] == "pipeline_step"]
    assert {step["run_id"] for step in steps} == {state["run_id"]}
    assert all("input" in step and "output" in step for step in steps)


def test_the_logs_never_contain_the_message_text(logs: Path) -> None:
    run(deps_for(order_llm(), order_transport()))

    assert MESSAGE_TEXT not in (logs / "data" / "logs" / "agent.log").read_text(encoding="utf-8")


def test_a_run_adds_the_items_and_reports_them_with_the_cart_total() -> None:
    transport = order_transport()

    state = run(deps_for(order_llm(), transport))

    report = state["report"]
    assert [(item.spin_id, item.quantity, item.sources) for item in report.added] == [
        ("ATTA-AS-1", 2, ["m1"])
    ]
    assert (report.skipped, str(report.total), report.dry_run) == ([], "120", False)
    update = next(call for call in transport.calls if call.name == "update_cart")
    assert update.arguments["items"] == [
        {"spinId": "ATTA-AS-1", "skuId": "SKU-AS-1", "quantity": 2}
    ]


def test_a_dry_run_does_everything_except_write_the_cart() -> None:
    transport = order_transport()

    state = run(deps_for(order_llm(), transport), dry_run=True)

    names = [call.name for call in transport.calls]
    assert "update_cart" not in names
    assert "get_cart" in names
    assert state["report"].dry_run is True
    assert [item.spin_id for item in state["report"].added] == ["ATTA-AS-1"]


@pytest.mark.parametrize("label", ["general", "unsure"])
def test_a_general_or_unsure_message_goes_straight_to_the_report_and_never_reaches_swiggy(
    label: str, logs: Path
) -> None:
    transport = FakeSwiggyTransport({})
    llm = FakeLLM(Intent.model_validate({"label": label}))

    state = run(deps_for(llm, transport))

    assert transport.calls == []
    assert step_nodes(logged_events(logs)) == ["classify", "report"]
    assert (state["report"].intent, state["report"].added) == (label, [])


def test_a_payload_with_extracted_items_starts_at_the_rule_book(logs: Path) -> None:
    llm = FakeLLM()
    payload: dict[str, object] = {
        "inbound_ids": ["m1", "m2"],
        "extracted": [{"name": "atta", "quantity": "2", "unit": "kg", "sources": ["m1", "m2"]}],
    }

    state = run(deps_for(llm, order_transport()), payload)

    assert llm.calls == []
    assert step_nodes(logged_events(logs)) == NODE_ORDER[2:]
    assert state["report"].added[0].sources == ["m1", "m2"]


def test_an_item_with_no_rule_is_reported_skipped_and_the_cart_is_not_touched() -> None:
    transport = FakeSwiggyTransport({})
    items = [ExtractedItem(name="dragonfruit", quantity=Decimal(1))]
    llm = FakeLLM(Intent(label="order"), Extraction(items=items))

    state = run(deps_for(llm, transport))

    assert transport.calls == []
    assert [(s.name, s.reason) for s in state["report"].skipped] == [("dragonfruit", "no_rule")]


def test_a_tool_that_is_not_on_the_allowlist_is_rejected_by_the_client_the_pipeline_uses() -> None:
    deps = deps_for(order_llm(), order_transport())

    with pytest.raises(BlockedToolError):
        asyncio.run(deps.swiggy.call_tool("checkout"))


def test_a_payload_without_inbound_ids_is_rejected() -> None:
    with pytest.raises(ValueError):
        run(deps_for(order_llm(), order_transport()), {"text": "milk"})


def wait_for_runs(db_path: Path, count: int) -> list[sqlite3.Row]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with connect(db_path) as reader:
            rows = reader.execute("SELECT * FROM runs").fetchall()
        if len(rows) >= count:
            return rows
        time.sleep(0.02)
    raise AssertionError("no run was recorded")


def test_an_inbound_message_flows_through_the_consumer_worker_and_graph_to_the_cart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat2cart.sqlite"
    with connect(db_path) as conn:
        migrate(conn)
        conn.execute(
            "INSERT INTO inbound_messages (id, chat_jid, sender_jid, sender_pn, text, received_at)"
            " VALUES ('m1', 'chat', 'sender', '919876543210', ?, '2026-11-07T09:00:00Z')",
            (MESSAGE_TEXT,),
        )
        conn.commit()
    transport = order_transport()
    deps = deps_for(order_llm(), transport)

    @contextmanager
    def open_deps() -> Iterator[PipelineDeps]:
        yield deps

    worker = start_cart_worker(db_path, pipeline_job_handler(db_path, open_deps), 0.01)
    inbox = start_inbox_consumer(db_path, enqueue_message_job)
    try:
        (run_row,) = wait_for_runs(db_path, 1)
    finally:
        inbox.stop()
        worker.stop()

    report = json.loads(run_row["result_json"])
    assert [item["spin_id"] for item in report["added"]] == ["ATTA-AS-1"]
    assert report["sources"] == ["m1"]
    update = next(call for call in transport.calls if call.name == "update_cart")
    assert update.arguments["items"] == [
        {"spinId": "ATTA-AS-1", "skuId": "SKU-AS-1", "quantity": 2}
    ]
    with connect(db_path) as reader:
        statuses = [
            reader.execute("SELECT status FROM inbound_messages").fetchone()["status"],
            reader.execute("SELECT status FROM cart_jobs").fetchone()["status"],
        ]
    assert statuses == ["done", "done"]
