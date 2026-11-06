import asyncio
from decimal import Decimal

import pytest
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.swiggy.cart import CartWriteResult, read_cart, write_cart
from chat2cart.swiggy.errors import BadInputError, SwiggyError

ADDRESS_ID = "addr-002"


def test_read_cart_returns_items_ids_quantities_and_the_bill_total() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("get_cart_two_items"))

    cart = asyncio.run(read_cart(logged_in_client(transport)))

    assert [(item.spin_id, item.sku_id, item.quantity) for item in cart.items] == [
        ("0A1B2C3D", "000123456", 2),
        ("0B2C3D4E", "000987654", 1),
    ]
    assert cart.bill_total == Decimal("93.5")
    assert [call.name for call in transport.calls] == ["get_cart"]


def test_a_normal_write_sends_every_line_and_the_address_in_one_call() -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("get_cart_two_items"), load_swiggy_fixture("update_cart_ok")
    )
    client = logged_in_client(transport)

    async def read_then_write() -> CartWriteResult:
        cart = await read_cart(client)
        return await write_cart(client, cart.items, ADDRESS_ID)

    result = asyncio.run(read_then_write())

    update_calls = [call for call in transport.calls if call.name == "update_cart"]
    assert len(update_calls) == 1
    assert update_calls[0].arguments == {
        "selectedAddressId": ADDRESS_ID,
        "items": [
            {"spinId": "0A1B2C3D", "skuId": "000123456", "quantity": 2},
            {"spinId": "0B2C3D4E", "skuId": "000987654", "quantity": 1},
        ],
    }
    assert (result.removed, result.reduced) == ([], [])


def test_a_removed_out_of_stock_item_is_reported() -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("get_cart_two_items"), load_swiggy_fixture("update_cart_removed_oos")
    )
    client = logged_in_client(transport)

    async def run() -> list[str]:
        cart = await read_cart(client)
        result = await write_cart(client, cart.items, ADDRESS_ID)
        return [item.sku_id for item in result.removed]

    assert asyncio.run(run()) == ["000123458"]


def test_a_reduced_quantity_reports_what_was_asked_and_what_was_applied() -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("get_cart_two_items"), load_swiggy_fixture("update_cart_reduced_qty")
    )
    client = logged_in_client(transport)

    async def run() -> tuple[int, int | None]:
        cart = await read_cart(client)
        result = await write_cart(client, cart.items, ADDRESS_ID)
        return result.reduced[0].quantity, result.reduced[0].requested_quantity

    assert asyncio.run(run()) == (3, 5)


def test_write_cart_says_in_its_docs_that_it_replaces_the_entire_cart() -> None:
    assert write_cart.__doc__ is not None
    assert write_cart.__doc__.startswith("Replaces the ENTIRE Instamart cart")


def test_an_empty_write_is_refused_before_anything_is_sent() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("update_cart_ok"))

    with pytest.raises(BadInputError):
        asyncio.run(write_cart(logged_in_client(transport), [], ADDRESS_ID))

    assert transport.calls == []


def test_an_unexpected_cart_shape_is_an_error() -> None:
    transport = FakeSwiggyTransport({"basket": []})

    with pytest.raises(SwiggyError, match="cart was not in the expected format"):
        asyncio.run(read_cart(logged_in_client(transport)))


def test_an_unreadable_write_answer_says_the_cart_may_have_changed() -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("get_cart_two_items"), {"removedOutOfStockItems": "oops"}
    )
    client = logged_in_client(transport)

    async def run() -> None:
        cart = await read_cart(client)
        await write_cart(client, cart.items, ADDRESS_ID)

    with pytest.raises(SwiggyError, match="Read the cart to see the result"):
        asyncio.run(run())
