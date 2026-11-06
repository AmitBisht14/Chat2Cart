import asyncio

import pytest
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.swiggy.errors import DomainError, SwiggyError
from chat2cart.swiggy.products import search


def test_search_asks_swiggy_for_the_query_and_the_address() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("search_products_milk"))

    asyncio.run(search(logged_in_client(transport), "milk", "addr-002"))

    assert [(call.name, call.arguments) for call in transport.calls] == [
        ("search_products", {"addressId": "addr-002", "query": "milk"})
    ]


def test_variant_ids_are_kept_exactly_as_returned() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("search_products_milk"))

    products = asyncio.run(search(logged_in_client(transport), "milk", "addr-002"))

    first = products[0].variants[0]
    assert (first.spin_id, first.sku_id) == ("0A1B2C3D", "000123456")
    assert first.pack_size == "500 ml"
    assert products[1].variants[0].price == 35.5


def test_out_of_stock_variants_are_kept_and_marked() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("search_products_milk"))

    products = asyncio.run(search(logged_in_client(transport), "milk", "addr-002"))

    toned = products[0]
    assert [variant.in_stock for variant in toned.variants] == [True, True, False]
    assert sum(len(product.variants) for product in products) == 5


def test_a_domain_failure_is_raised_after_one_call() -> None:
    failure = {"success": False, "code": "NOT_SERVICEABLE", "message": "No delivery here"}
    transport = FakeSwiggyTransport(failure)

    with pytest.raises(DomainError):
        asyncio.run(search(logged_in_client(transport), "milk", "addr-002"))

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"products": [{"name": "Milk", "brand": "B", "variants": [{"spinId": 123}]}]},
    ],
)
def test_an_unexpected_shape_is_an_error_not_an_empty_result(payload: dict[str, object]) -> None:
    transport = FakeSwiggyTransport(payload)

    with pytest.raises(SwiggyError, match="not in the expected format"):
        asyncio.run(search(logged_in_client(transport), "milk", "addr-002"))
