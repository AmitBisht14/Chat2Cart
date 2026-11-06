import json
from datetime import UTC, datetime, timedelta

import httpx

from chat2cart.secrets import SWIGGY_CLIENT, SWIGGY_TOKENS, InMemorySecretStore
from chat2cart.swiggy.tokens import TokenManager

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


class FakeTokenEndpoint:
    """Stands in for Swiggy's /auth/token: every refresh returns access-2 and refresh-2."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._response is not None:
            return self._response
        return httpx.Response(
            200, json={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))


def stored_tokens(store: InMemorySecretStore, seconds_left: int) -> None:
    store.set(SWIGGY_CLIENT, json.dumps({"client_id": "client-1"}))
    store.set(
        SWIGGY_TOKENS,
        json.dumps(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_at": (NOW + timedelta(seconds=seconds_left)).isoformat(),
            }
        ),
    )


def manager_for(store: InMemorySecretStore, endpoint: FakeTokenEndpoint) -> TokenManager:
    return TokenManager(store, endpoint.client(), clock=lambda: NOW)
