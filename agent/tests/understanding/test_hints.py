import asyncio
from decimal import Decimal

from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.understanding.hints import load_hints, spin_ids_in
from chat2cart.understanding.resolve import resolve_items
from chat2cart.understanding.schemas import PreferencedItem

ADDRESS_ID = "addr-002"
SEARCH_FAILURE: dict[str, object] = {"success": False, "code": "SERVER_ERROR", "message": "down"}


def eggs(brands: list[str], size: str | None = None) -> PreferencedItem:
    return PreferencedItem.model_validate(
        {
            "name": "eggs",
            "quantity": Decimal(1),
            "unit": None,
            "brands": brands,
            "size": size,
            "substitute": "never",
        }
    )


def run(
    transport: FakeSwiggyTransport, items: list[PreferencedItem]
) -> tuple[list[str], list[str]]:
    resolved, skipped = asyncio.run(resolve_items(items, logged_in_client(transport), ADDRESS_ID))
    return [r.spin_id for r in resolved], [s.reason for s in skipped]


def transport_with(go_to: str, orders: str, *searches: str) -> FakeSwiggyTransport:
    return FakeSwiggyTransport(
        load_swiggy_fixture(go_to),
        load_swiggy_fixture(orders),
        *(load_swiggy_fixture(search) for search in searches),
    )


def test_go_to_items_and_orders_are_read_once_for_a_run_of_several_items() -> None:
    transport = transport_with(
        "your_go_to_items_usual", "get_orders_empty", "search_products_eggs", "search_products_eggs"
    )

    run(transport, [eggs(["Farm Fresh"], "30 pcs"), eggs(["Farm Fresh"], "6 pcs")])

    assert [call.name for call in transport.calls] == [
        "your_go_to_items",
        "get_orders",
        "search_products",
        "search_products",
    ]
    assert transport.calls[0].arguments == {"addressId": ADDRESS_ID}


def test_a_go_to_variant_breaks_a_tie_between_variants_that_already_fit() -> None:
    transport = transport_with("your_go_to_items_usual", "get_orders_empty", "search_products_eggs")

    chosen, skipped = run(transport, [eggs(["Farm Fresh"])])

    assert (chosen, skipped) == (["EGG-FF-12"], [])


def test_a_variant_from_a_recent_order_breaks_a_tie_too() -> None:
    transport = transport_with(
        "your_go_to_items_other_brand", "get_orders_recent", "search_products_eggs"
    )

    chosen, _ = run(transport, [eggs(["Farm Fresh"])])

    assert chosen == ["EGG-FF-6"]


def test_a_go_to_variant_of_a_brand_the_rule_book_excludes_is_never_chosen() -> None:
    transport = transport_with(
        "your_go_to_items_other_brand", "get_orders_empty", "search_products_eggs"
    )

    chosen, skipped = run(transport, [eggs(["Farm Fresh"])])

    assert (chosen, skipped) == ([], ["ambiguous"])


def test_hints_never_override_a_size_the_rule_book_asks_for() -> None:
    transport = transport_with("your_go_to_items_usual", "get_orders_empty", "search_products_eggs")

    chosen, _ = run(transport, [eggs(["Farm Fresh"], "30 pcs")])

    assert chosen == ["EGG-FF-30"]


def test_two_hinted_variants_that_fit_stay_ambiguous() -> None:
    transport = transport_with(
        "your_go_to_items_usual", "get_orders_recent", "search_products_eggs"
    )

    chosen, skipped = run(transport, [eggs(["Farm Fresh"])])

    assert (chosen, skipped) == ([], ["ambiguous"])


def test_when_the_hint_calls_fail_matching_still_returns_results() -> None:
    transport = FakeSwiggyTransport(SEARCH_FAILURE, load_swiggy_fixture("search_products_eggs"))

    chosen, skipped = run(transport, [eggs(["Farm Fresh"], "30 pcs")])

    assert (chosen, skipped) == (["EGG-FF-30"], [])
    assert [call.name for call in transport.calls] == ["your_go_to_items", "search_products"]


def test_failed_hint_calls_leave_a_tie_ambiguous_instead_of_guessing() -> None:
    transport = FakeSwiggyTransport(SEARCH_FAILURE, load_swiggy_fixture("search_products_eggs"))

    _, skipped = run(transport, [eggs(["Farm Fresh"])])

    assert skipped == ["ambiguous"]


def test_load_hints_collects_the_variant_ids_from_both_calls() -> None:
    transport = transport_with("your_go_to_items_usual", "get_orders_recent")

    hints = asyncio.run(load_hints(logged_in_client(transport), ADDRESS_ID))

    assert hints == {"EGG-FF-12", "ATTA-AS-5", "EGG-FF-6"}


def test_spin_ids_are_found_at_any_depth_and_other_values_are_ignored() -> None:
    payload = {
        "a": [{"b": {"spinId": "X1", "skuId": "S1"}}],
        "spinId": "X2",
        "n": 5,
        "spinId2": "no",
    }

    assert spin_ids_in(payload) == {"X1", "X2"}
