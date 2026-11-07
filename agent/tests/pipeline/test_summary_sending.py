import asyncio
from decimal import Decimal

import pytest
from fakes.fake_llm import FakeLLM
from fakes.notify import RecordingNotify
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.pipeline.graph import run_pipeline
from chat2cart.pipeline.state import OrderState, PipelineDeps
from chat2cart.understanding.rulebook import parse_rulebook
from chat2cart.understanding.schemas import ExtractedItem, Extraction, Intent

RULEBOOK = parse_rulebook("## Atta\n- brand: Aashirvaad\n- size: 1 kg\n- default_quantity: 1\n")
EMPTY_CART: dict[str, object] = {"items": [], "cartTotalAmount": "0", "cartAbsent": True}


def cart_after(total: str) -> dict[str, object]:
    line = {"spinId": "ATTA-AS-1", "skuId": "SKU-AS-1", "itemName": "Atta", "quantity": 2}
    return {"items": [line], "cartTotalAmount": total, "cartAbsent": False}


def order_transport(total: str = "120") -> FakeSwiggyTransport:
    return FakeSwiggyTransport(
        {"items": []},
        {"orders": []},
        load_swiggy_fixture("search_products_atta"),
        EMPTY_CART,
        load_swiggy_fixture("update_cart_ok"),
        cart_after(total),
    )


def order_llm() -> FakeLLM:
    items = [ExtractedItem(name="atta", quantity=Decimal(2), unit="kg")]
    return FakeLLM(Intent(label="order"), Extraction(items=items))


def run(
    llm: FakeLLM,
    transport: FakeSwiggyTransport,
    notify: RecordingNotify,
    dry_run: bool = False,
) -> OrderState:
    deps = PipelineDeps(
        llm=llm,
        swiggy=logged_in_client(transport),
        load_rulebook=lambda: RULEBOOK,
        address_id="addr-002",
        notify=notify,
    )
    payload: dict[str, object] = {"inbound_ids": ["m1"], "text": "2 kg atta"}
    return asyncio.run(run_pipeline(payload, deps, dry_run))


def test_a_cart_update_sends_one_summary_with_the_composed_text() -> None:
    notify = RecordingNotify()

    state = run(order_llm(), order_transport(), notify)

    ((kind, title, body),) = notify.sent
    assert (kind, title) == ("summary", "Cart updated")
    assert "Added: Aashirvaad Atta x 2" in body
    assert "Total: ₹120" in body
    assert "Keep the Swiggy app closed" in body
    assert state["report"].total == Decimal("120")


def test_a_cart_under_the_minimum_says_so_in_the_summary() -> None:
    notify = RecordingNotify()

    run(order_llm(), order_transport(total="98"), notify)

    assert "Below the ₹99 minimum order." in notify.sent[0][2]


def test_a_dry_run_sends_no_summary() -> None:
    notify = RecordingNotify()

    run(order_llm(), order_transport(), notify, dry_run=True)

    assert notify.sent == []


@pytest.mark.parametrize("label", ["general", "unsure"])
def test_a_message_that_is_not_an_order_sends_no_summary(label: str) -> None:
    notify = RecordingNotify()

    run(FakeLLM(Intent.model_validate({"label": label})), FakeSwiggyTransport({}), notify)

    assert notify.sent == []


def test_a_run_that_writes_no_cart_sends_no_summary() -> None:
    notify = RecordingNotify()
    items = [ExtractedItem(name="dragonfruit", quantity=Decimal(1))]
    llm = FakeLLM(Intent(label="order"), Extraction(items=items))

    run(llm, FakeSwiggyTransport({}), notify)

    assert notify.sent == []


def test_a_failed_send_does_not_break_the_run() -> None:
    notify = RecordingNotify(result=False)

    state = run(order_llm(), order_transport(), notify)

    assert len(notify.sent) == 1
    assert [item.spin_id for item in state["report"].added] == ["ATTA-AS-1"]
