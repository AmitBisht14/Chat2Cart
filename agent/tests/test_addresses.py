import asyncio

import pytest
from fakes.swiggy import FakeSwiggyTransport, RecordingSleep, load_swiggy_fixture
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens

from chat2cart.secrets import InMemorySecretStore
from chat2cart.swiggy.addresses import Address, list_addresses, parse_page
from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError


def client_for(transport: FakeSwiggyTransport) -> SwiggyClient:
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=3600)
    return SwiggyClient(manager_for(store, FakeTokenEndpoint()), transport, RecordingSleep())


def test_a_server_that_ignores_the_page_number_does_not_loop_forever() -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("get_addresses_page1"))

    addresses = asyncio.run(list_addresses(client_for(transport)))

    assert len(addresses) == 10
    assert len(transport.calls) == 2


def test_a_page_that_says_there_is_no_next_page_stops_the_listing() -> None:
    full_page = load_swiggy_fixture("get_addresses_page1")
    data = full_page["data"]
    assert isinstance(data, dict)
    transport = FakeSwiggyTransport({**full_page, "data": {**data, "hasNextPage": False}})

    asyncio.run(list_addresses(client_for(transport)))

    assert len(transport.calls) == 1


def test_description_shows_every_text_field_except_the_id() -> None:
    page = parse_page(load_swiggy_fixture("get_addresses_page2"))

    assert page.addresses[0] == Address("addr-011", "Parents | 11 Example Street, Bengaluru")


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True},
        {"data": {"addresses": "none"}},
        {"data": {"addresses": [{"annotation": "Home"}]}},
    ],
)
def test_an_unexpected_shape_is_an_error(payload: dict[str, object]) -> None:
    with pytest.raises(SwiggyError):
        parse_page(payload)
