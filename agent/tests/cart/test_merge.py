import asyncio
from decimal import Decimal

from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.cart.merge import CartDiff, MergeResult, merge_into_cart
from chat2cart.understanding.schemas import ResolvedItem

ADDRESS_ID = "addr-002"
HAND_ADDED = "0A1B2C3D"  # in get_cart_two_items, 2 x Example Dairy Toned Milk
SECOND_LINE = "0B2C3D4E"  # in get_cart_two_items, 1 x Sample Farms Full Cream Milk


def new_item(spin_id: str, quantity: int, name: str = "Atta 1 kg") -> ResolvedItem:
    return ResolvedItem(
        name="atta", spin_id=spin_id, sku_id=f"sku-{spin_id}", variant_name=name, quantity=quantity
    )


def cart_payload(*lines: tuple[str, int], total: str = "100") -> dict[str, object]:
    return {
        "items": [
            {"spinId": spin, "skuId": f"sku-{spin}", "itemName": f"item {spin}", "quantity": qty}
            for spin, qty in lines
        ],
        "cartTotalAmount": total,
        "cartAbsent": False,
    }


def merge(
    transport: FakeSwiggyTransport, items: list[ResolvedItem], dry_run: bool = False
) -> MergeResult:
    client = logged_in_client(transport)
    return asyncio.run(merge_into_cart(client, ADDRESS_ID, items, dry_run))


def written_lines(transport: FakeSwiggyTransport) -> list[tuple[str, int]]:
    (update,) = [call for call in transport.calls if call.name == "update_cart"]
    items = update.arguments["items"]
    assert isinstance(items, list)
    return [(line["spinId"], line["quantity"]) for line in items]


def test_hand_added_items_are_kept_in_the_written_payload() -> None:
    cart = load_swiggy_fixture("get_cart_two_items")
    transport = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_ok"), cart)

    merge(transport, [new_item("ATTA-1", 1)])

    assert written_lines(transport) == [(HAND_ADDED, 2), (SECOND_LINE, 1), ("ATTA-1", 1)]


def test_the_same_variant_in_the_cart_and_the_request_is_one_line_with_the_larger_quantity() -> (
    None
):
    cart = load_swiggy_fixture("get_cart_two_items")
    transport = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_ok"), cart)

    merge(transport, [new_item(HAND_ADDED, 5)])

    assert written_lines(transport) == [(HAND_ADDED, 5), (SECOND_LINE, 1)]


def test_a_retried_job_does_not_double_a_quantity_already_in_the_cart() -> None:
    cart = load_swiggy_fixture("get_cart_two_items")
    transport = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_ok"), cart)

    merge(transport, [new_item(HAND_ADDED, 2)])

    assert written_lines(transport) == [(HAND_ADDED, 2), (SECOND_LINE, 1)]


def test_the_full_merged_list_is_written_in_a_single_update_call() -> None:
    cart = load_swiggy_fixture("get_cart_two_items")
    transport = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_ok"), cart)

    merge(transport, [new_item("ATTA-1", 1), new_item("RICE-1", 2)])

    assert [call.name for call in transport.calls] == ["get_cart", "update_cart", "get_cart"]
    assert transport.calls[1].arguments["selectedAddressId"] == ADDRESS_ID
    assert len(written_lines(transport)) == 4


def test_a_matching_read_back_reports_no_difference_and_the_bill_total() -> None:
    before = cart_payload(("A", 1))
    after = cart_payload(("A", 1), ("B", 2), total="180")
    transport = FakeSwiggyTransport(before, load_swiggy_fixture("update_cart_ok"), after)

    result = merge(transport, [new_item("B", 2)])

    assert (result.diffs, result.bill_total) == ([], Decimal("180"))


def test_a_different_read_back_cart_is_reported_as_missing_changed_and_unexpected() -> None:
    before = cart_payload(("A", 1))
    after = cart_payload(("A", 3), ("C", 1))
    transport = FakeSwiggyTransport(before, load_swiggy_fixture("update_cart_ok"), after)

    result = merge(transport, [new_item("B", 2)])

    assert result.diffs == [
        CartDiff("A", intended=1, actual=3),
        CartDiff("B", intended=2, actual=None),
        CartDiff("C", intended=None, actual=1),
    ]


def test_items_swiggy_removed_or_reduced_are_reported() -> None:
    cart = load_swiggy_fixture("get_cart_two_items")
    removed = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_removed_oos"), cart)
    reduced = FakeSwiggyTransport(cart, load_swiggy_fixture("update_cart_reduced_qty"), cart)

    removed_result = merge(removed, [new_item("ATTA-1", 1)])
    reduced_result = merge(reduced, [new_item("ATTA-1", 1)])

    assert [item.sku_id for item in removed_result.removed] == ["000123458"]
    assert [(item.requested_quantity, item.capped_quantity) for item in reduced_result.reduced] == [
        (99, 20)
    ]


def test_a_dry_run_reads_the_cart_but_writes_nothing() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("get_cart_two_items"))

    result = merge(transport, [new_item("ATTA-1", 1)], dry_run=True)

    assert [call.name for call in transport.calls] == ["get_cart"]
    assert [item.spin_id for item in result.intended] == [HAND_ADDED, SECOND_LINE, "ATTA-1"]
    assert result.actual is None


def test_nothing_new_to_add_leaves_the_cart_alone() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("get_cart_two_items"))

    result = merge(transport, [])

    assert [call.name for call in transport.calls] == ["get_cart"]
    assert [item.spin_id for item in result.intended] == [HAND_ADDED, SECOND_LINE]


def test_an_empty_cart_gets_just_the_new_items() -> None:
    transport = FakeSwiggyTransport(
        cart_payload(), load_swiggy_fixture("update_cart_ok"), cart_payload(("ATTA-1", 1))
    )

    result = merge(transport, [new_item("ATTA-1", 1)])

    assert (written_lines(transport), result.diffs) == ([("ATTA-1", 1)], [])
