import asyncio

import pytest
from fakes.swiggy import FakeSwiggyTransport, RecordingSleep
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens
from structlog.testing import capture_logs

from chat2cart.secrets import InMemorySecretStore
from chat2cart.swiggy.client import MAX_ATTEMPTS, SwiggyClient
from chat2cart.swiggy.errors import AuthError, BadInputError, DomainError, UpstreamError

OK = {"success": True, "items": []}


def client_with(
    transport: FakeSwiggyTransport, endpoint: FakeTokenEndpoint | None = None
) -> tuple[SwiggyClient, RecordingSleep]:
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=3600)
    sleep = RecordingSleep()
    tokens = manager_for(store, endpoint or FakeTokenEndpoint())
    return SwiggyClient(tokens, transport, sleep), sleep


def test_timeout_then_success_makes_two_calls() -> None:
    transport = FakeSwiggyTransport(UpstreamError("timed out"), OK)
    client, _ = client_with(transport)

    payload = asyncio.run(client.call_tool("get_cart"))

    assert payload == OK
    assert len(transport.calls) == 2


def test_server_errors_stop_after_five_attempts_with_bounded_backoff() -> None:
    transport = FakeSwiggyTransport(UpstreamError("HTTP 503"))
    client, sleep = client_with(transport)

    with pytest.raises(UpstreamError):
        asyncio.run(client.call_tool("get_cart"))

    assert len(transport.calls) == MAX_ATTEMPTS == 5
    assert len(sleep.waits) == 4
    assert all(0 <= wait <= 8 for wait in sleep.waits)


def test_rate_limit_waits_for_retry_after() -> None:
    transport = FakeSwiggyTransport(UpstreamError("rate limited", retry_after=3), OK)
    client, sleep = client_with(transport)

    asyncio.run(client.call_tool("get_cart"))

    assert sleep.waits == [3]


def test_domain_failure_is_raised_after_exactly_one_call() -> None:
    failure = {"success": False, "code": "ADDRESS_NOT_SERVICEABLE", "message": "No delivery"}
    transport = FakeSwiggyTransport(failure)
    client, sleep = client_with(transport)

    with pytest.raises(DomainError) as error_info:
        asyncio.run(client.call_tool("update_cart"))

    assert error_info.value.code == "ADDRESS_NOT_SERVICEABLE"
    assert error_info.value.message == "No delivery"
    assert len(transport.calls) == 1
    assert sleep.waits == []


def test_bad_input_is_raised_after_exactly_one_call() -> None:
    transport = FakeSwiggyTransport(BadInputError("bad arguments"))
    client, _ = client_with(transport)

    with pytest.raises(BadInputError):
        asyncio.run(client.call_tool("search_products", {"query": ""}))

    assert len(transport.calls) == 1


def test_expired_token_refreshes_once_then_succeeds() -> None:
    transport = FakeSwiggyTransport(AuthError("expired", status=401), OK)
    endpoint = FakeTokenEndpoint()
    client, _ = client_with(transport, endpoint)

    payload = asyncio.run(client.call_tool("get_cart"))

    assert payload == OK
    assert len(endpoint.requests) == 1
    assert [call.token for call in transport.calls] == ["access-1", "access-2"]


def test_logs_name_the_tool_and_argument_keys_but_never_tokens_or_values() -> None:
    transport = FakeSwiggyTransport(AuthError("expired", status=401), OK)
    client, _ = client_with(transport)

    with capture_logs() as logs:
        asyncio.run(client.call_tool("search_products", {"query": "organic milk"}))

    events = [entry["event"] for entry in logs]
    assert events.count("swiggy_call") == 1
    assert events.count("swiggy_result") == 1
    assert {"tool": "search_products", "argument_keys": ["query"]}.items() <= logs[0].items()
    written = str(logs)
    assert "access-1" not in written
    assert "access-2" not in written
    assert "organic milk" not in written
