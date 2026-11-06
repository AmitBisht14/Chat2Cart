import asyncio
import socket

import pytest
from fakes.mcp_server import FakeMcpServer

from chat2cart.swiggy.client import McpTransport
from chat2cart.swiggy.errors import AuthError, BadInputError, SwiggyError, UpstreamError

TOKEN = "token-123"


def call(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    transport = McpTransport(url=url, timeout_seconds=timeout_seconds)
    return asyncio.run(transport(TOKEN, "get_cart", {}))


def test_a_tool_call_sends_the_bearer_token_and_returns_the_json_result() -> None:
    with FakeMcpServer(tool_payload={"success": True, "items": [1]}) as server:
        payload = call(server.url)

    assert payload == {"success": True, "items": [1]}
    assert server.requests == [
        ("initialize", "Bearer token-123"),
        ("notifications/initialized", "Bearer token-123"),
        ("tools/call", "Bearer token-123"),
    ]


def test_http_401_is_an_auth_error_with_its_status() -> None:
    with FakeMcpServer(fail_status=401) as server, pytest.raises(AuthError) as error_info:
        call(server.url)

    assert error_info.value.status == 401


def test_http_429_is_an_upstream_error_carrying_retry_after() -> None:
    with FakeMcpServer(fail_status=429, retry_after="3") as server:
        with pytest.raises(UpstreamError) as error_info:
            call(server.url)

    assert error_info.value.retry_after == 3


def test_http_5xx_is_an_upstream_error() -> None:
    with FakeMcpServer(fail_status=503) as server, pytest.raises(UpstreamError):
        call(server.url)


def test_http_400_is_a_bad_input_error() -> None:
    with FakeMcpServer(fail_status=400) as server, pytest.raises(BadInputError):
        call(server.url)


def test_other_http_failures_are_a_plain_swiggy_error_and_not_retryable() -> None:
    with FakeMcpServer(fail_status=403) as server:
        with pytest.raises(SwiggyError) as error_info:
            call(server.url)

    assert not isinstance(error_info.value, UpstreamError | AuthError | BadInputError)


def test_a_slow_server_is_an_upstream_error() -> None:
    with FakeMcpServer(delay_seconds=1.0) as server, pytest.raises(UpstreamError):
        call(server.url, timeout_seconds=0.2)


def test_an_unreachable_server_is_an_upstream_error() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    with pytest.raises(UpstreamError):
        call(f"http://127.0.0.1:{closed_port}/im")
