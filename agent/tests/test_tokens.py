import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fakes.tokens import FakeTokenEndpoint, manager_for, stored_tokens

from chat2cart.secrets import SWIGGY_TOKENS, InMemorySecretStore
from chat2cart.swiggy.errors import AuthError, NeedsLoginError
from chat2cart.swiggy.tokens import call_with_auth_retry


@pytest.mark.parametrize(
    ("seconds_left", "expected_token", "expected_refreshes"),
    [(61, "access-1", 0), (60, "access-2", 1)],
)
def test_token_is_refreshed_when_60_seconds_or_less_remain(
    seconds_left: int, expected_token: str, expected_refreshes: int
) -> None:
    store, endpoint = InMemorySecretStore(), FakeTokenEndpoint()
    stored_tokens(store, seconds_left)

    token = manager_for(store, endpoint).ensure_fresh()

    assert token == expected_token
    assert len(endpoint.requests) == expected_refreshes


def test_refresh_stores_the_new_refresh_token_and_discards_the_old_one() -> None:
    store, endpoint = InMemorySecretStore(), FakeTokenEndpoint()
    stored_tokens(store, seconds_left=10)

    manager_for(store, endpoint).refresh()

    sent = parse_qs(endpoint.requests[0].content.decode())
    assert sent["grant_type"] == ["refresh_token"]
    assert sent["refresh_token"] == ["refresh-1"]
    assert sent["client_id"] == ["client-1"]
    stored = json.loads(store.get(SWIGGY_TOKENS) or "{}")
    assert stored["refresh_token"] == "refresh-2"
    assert stored["access_token"] == "access-2"
    assert "refresh-1" not in (store.get(SWIGGY_TOKENS) or "")


@pytest.mark.parametrize("failure", [{"status": 401}, {"rpc_code": -32001}])
def test_auth_failure_refreshes_once_and_retries_once(failure: dict[str, int]) -> None:
    store, endpoint = InMemorySecretStore(), FakeTokenEndpoint()
    stored_tokens(store, seconds_left=3600)
    tokens_used: list[str] = []

    async def call(token: str) -> str:
        tokens_used.append(token)
        if len(tokens_used) == 1:
            raise AuthError("expired", **failure)
        return "ok"

    result = asyncio.run(call_with_auth_retry(manager_for(store, endpoint), call))

    assert result == "ok"
    assert tokens_used == ["access-1", "access-2"]
    assert len(endpoint.requests) == 1


def test_a_second_auth_failure_is_not_retried_again() -> None:
    store, endpoint = InMemorySecretStore(), FakeTokenEndpoint()
    stored_tokens(store, seconds_left=3600)
    calls: list[str] = []

    async def call(token: str) -> str:
        calls.append(token)
        raise AuthError("expired", status=401)

    with pytest.raises(AuthError):
        asyncio.run(call_with_auth_retry(manager_for(store, endpoint), call))

    assert len(calls) == 2
    assert len(endpoint.requests) == 1


def test_invalid_grant_marks_the_session_as_needing_login() -> None:
    store = InMemorySecretStore()
    endpoint = FakeTokenEndpoint(httpx.Response(400, json={"error": "invalid_grant"}))
    stored_tokens(store, seconds_left=10)
    manager = manager_for(store, endpoint)

    with pytest.raises(NeedsLoginError, match="chat2cart login swiggy"):
        manager.refresh()

    assert manager.needs_login()
    with pytest.raises(NeedsLoginError):
        manager.ensure_fresh()
    assert len(endpoint.requests) == 1


def test_missing_tokens_ask_for_a_login() -> None:
    manager = manager_for(InMemorySecretStore(), FakeTokenEndpoint())

    with pytest.raises(NeedsLoginError, match="chat2cart login swiggy"):
        manager.ensure_fresh()
    assert manager.needs_login()
