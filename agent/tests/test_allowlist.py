import asyncio

import pytest
from fakes.mcp_server import FakeMcpServer
from fakes.swiggy import FakeSwiggyTransport, RecordingSleep
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens
from structlog.testing import capture_logs

from chat2cart.secrets import InMemorySecretStore
from chat2cart.swiggy.allowlist import ALLOWED_TOOLS
from chat2cart.swiggy.client import McpTransport, SwiggyClient
from chat2cart.swiggy.errors import BlockedToolError

BLOCKED_TOOLS = [
    "checkout",
    "get_payment_options",
    "check_payment_status",
    "confirm_order",
    "clear_cart",
    "unknown_future_tool",
    "Get_Cart",
    "",
]


def client_without_tokens(transport: FakeSwiggyTransport) -> SwiggyClient:
    # With no stored tokens, any token lookup would raise NeedsLoginError instead.
    tokens = manager_for(InMemorySecretStore(), FakeTokenEndpoint())
    return SwiggyClient(tokens, transport, RecordingSleep())


def test_allowed_tools_are_exactly_the_seven_from_the_plan() -> None:
    assert ALLOWED_TOOLS == {
        "get_addresses",
        "search_products",
        "your_go_to_items",
        "get_cart",
        "update_cart",
        "get_orders",
        "get_order_details",
    }


@pytest.mark.parametrize("tool", BLOCKED_TOOLS)
def test_blocked_tool_is_rejected_before_any_token_lookup_or_request(tool: str) -> None:
    transport = FakeSwiggyTransport({"success": True})
    client = client_without_tokens(transport)

    with pytest.raises(BlockedToolError):
        asyncio.run(client.call_tool(tool))

    assert transport.calls == []


@pytest.mark.parametrize("tool", sorted(ALLOWED_TOOLS))
def test_every_allowed_tool_reaches_the_transport(tool: str) -> None:
    transport = FakeSwiggyTransport({"success": True})
    store = InMemorySecretStore()
    stored_tokens(store, seconds_left=3600)
    client = SwiggyClient(manager_for(store, FakeTokenEndpoint()), transport, RecordingSleep())

    asyncio.run(client.call_tool(tool))

    assert [call.name for call in transport.calls] == [tool]


def test_a_blocked_call_is_logged_as_a_security_event() -> None:
    client = client_without_tokens(FakeSwiggyTransport({"success": True}))

    with capture_logs() as logs, pytest.raises(BlockedToolError):
        asyncio.run(client.call_tool("checkout"))

    assert {"event": "security_blocked_tool", "log_level": "warning", "tool": "checkout"} in logs


@pytest.mark.parametrize("tool", BLOCKED_TOOLS)
def test_the_real_transport_refuses_blocked_tools_even_when_called_directly(tool: str) -> None:
    with FakeMcpServer() as server:
        transport = McpTransport(url=server.url)

        with pytest.raises(BlockedToolError):
            asyncio.run(transport("token", tool, {}))

    assert server.requests == []
