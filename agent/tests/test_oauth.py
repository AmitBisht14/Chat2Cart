import json
import socket
import threading
import urllib.request
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from typer.testing import CliRunner

from chat2cart.cli import app
from chat2cart.secrets import SWIGGY_CLIENT, SWIGGY_TOKENS, InMemorySecretStore
from chat2cart.swiggy.errors import AuthError
from chat2cart.swiggy.oauth import challenge_for, generate_pkce, login

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class FakeSwiggy:
    def __init__(self, *, reject_registration: bool = False) -> None:
        self.reject_registration = reject_registration
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/auth/register":
            if self.reject_registration:
                return httpx.Response(400, json={"error": "invalid_redirect_uri"})
            return httpx.Response(201, json={"client_id": "client-1"})
        return httpx.Response(
            200, json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def token_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/auth/token"]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BrowserFake:
    def __init__(self, port: int, state: str | None = None) -> None:
        self.port = port
        self.state = state
        self.authorize_url = ""
        self.thread: threading.Thread | None = None

    def __call__(self, url: str) -> None:
        self.authorize_url = url
        state = self.state or parse_qs(urlparse(url).query)["state"][0]
        callback = f"http://127.0.0.1:{self.port}/callback?code=code-1&state={state}"
        self.thread = threading.Thread(target=lambda: urllib.request.urlopen(callback).read())
        self.thread.start()

    def finish(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=5)


def test_pkce_challenge_matches_rfc_7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_generated_pkce_pair_is_random_and_consistent() -> None:
    first, second = generate_pkce(), generate_pkce()

    assert first.verifier != second.verifier
    assert len(first.verifier) >= 43
    assert first.challenge == challenge_for(first.verifier)


def test_state_mismatch_is_rejected_without_exchanging_the_code() -> None:
    swiggy, store, port = FakeSwiggy(), InMemorySecretStore(), free_port()
    browser = BrowserFake(port, state="wrong-state")

    with pytest.raises(AuthError, match="state mismatch"):
        login(store, swiggy.client(), open_browser=browser, callback_port=port, now=lambda: NOW)
    browser.finish()

    assert swiggy.token_requests() == []
    assert store.get(SWIGGY_TOKENS) is None


def test_login_registers_the_client_and_stores_tokens_with_expiry() -> None:
    swiggy, store, port = FakeSwiggy(), InMemorySecretStore(), free_port()
    browser = BrowserFake(port)

    login(store, swiggy.client(), open_browser=browser, callback_port=port, now=lambda: NOW)
    browser.finish()

    registration = json.loads(swiggy.requests[0].content)
    assert registration["redirect_uris"] == ["http://localhost/callback"]
    assert registration["token_endpoint_auth_method"] == "none"
    assert parse_qs(urlparse(browser.authorize_url).query)["code_challenge_method"] == ["S256"]
    assert json.loads(store.get(SWIGGY_CLIENT) or "{}")["client_id"] == "client-1"
    assert json.loads(store.get(SWIGGY_TOKENS) or "{}") == {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_at": "2026-11-05T13:00:00+00:00",
    }
    with pytest.raises(ConnectionRefusedError), socket.create_connection(("127.0.0.1", port)):
        pass


def test_rejected_redirect_explains_the_fix() -> None:
    swiggy = FakeSwiggy(reject_registration=True)

    with pytest.raises(AuthError, match=r"http://localhost/callback"):
        login(InMemorySecretStore(), swiggy.client(), open_browser=lambda url: None)


def test_login_command_prints_the_guidance_for_a_rejected_redirect(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
) -> None:
    def rejected(*args: object, **kwargs: object) -> None:
        raise AuthError("Swiggy only accepts http://localhost/callback as the redirect address.")

    monkeypatch.setattr("chat2cart.cli.swiggy_login", rejected)
    monkeypatch.setattr("chat2cart.cli.build_secret_store", InMemorySecretStore)

    result = CliRunner().invoke(app, ["login", "swiggy"])

    assert result.exit_code == 1
    assert "http://localhost/callback" in result.output
