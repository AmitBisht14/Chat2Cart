import json

import httpx
import pytest
from fakes.tokens import stored_tokens
from typer.testing import CliRunner

from chat2cart.cli import app
from chat2cart.secrets import SWIGGY_CLIENT, SWIGGY_TOKENS, InMemorySecretStore

LOGOUT_URL = "https://mcp.swiggy.com/auth/logout"


class FakeSwiggyLogout:
    """Stands in for Swiggy's /auth/logout and records every request it gets."""

    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status = status
        self._error = error

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return httpx.Response(self._status, json={})


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> InMemorySecretStore:
    in_memory = InMemorySecretStore()
    stored_tokens(in_memory, seconds_left=3600)
    monkeypatch.setattr("chat2cart.cli.build_secret_store", lambda: in_memory)
    return in_memory


def use_swiggy(monkeypatch: pytest.MonkeyPatch, swiggy: FakeSwiggyLogout) -> None:
    monkeypatch.setattr(
        "chat2cart.cli.build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(swiggy.handle)),
    )


def logout(answer: str = "y\n") -> tuple[int, str]:
    result = CliRunner().invoke(app, ["logout", "swiggy"], input=answer)
    return result.exit_code, result.output


def test_confirm_yes_revokes_the_session_and_deletes_the_tokens(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    swiggy = FakeSwiggyLogout()
    use_swiggy(monkeypatch, swiggy)

    code, output = logout()

    (request,) = swiggy.requests
    assert (request.method, str(request.url)) == ("POST", LOGOUT_URL)
    assert request.headers["authorization"] == "Bearer access-1"
    assert (code, store.get(SWIGGY_TOKENS)) == (0, None)
    assert "Logged out of Swiggy" in output


def test_confirm_no_changes_nothing(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    swiggy = FakeSwiggyLogout()
    use_swiggy(monkeypatch, swiggy)

    code, _ = logout("n\n")

    assert code != 0
    assert swiggy.requests == []
    assert store.get(SWIGGY_TOKENS) is not None


def test_the_command_asks_before_acting(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_swiggy(monkeypatch, FakeSwiggyLogout())

    _, output = logout()

    assert "Log out of Swiggy and delete stored tokens?" in output


def test_with_no_tokens_it_says_so_and_does_nothing(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.delete(SWIGGY_TOKENS)
    swiggy = FakeSwiggyLogout()
    use_swiggy(monkeypatch, swiggy)

    code, output = logout("")

    assert (code, swiggy.requests) == (0, [])
    assert "Not logged in" in output


def test_a_401_counts_as_logged_out_without_a_warning(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_swiggy(monkeypatch, FakeSwiggyLogout(status=401))

    code, output = logout()

    assert (code, store.get(SWIGGY_TOKENS)) == (0, None)
    assert "Warning" not in output


@pytest.mark.parametrize(
    "swiggy",
    [FakeSwiggyLogout(status=500), FakeSwiggyLogout(error=httpx.ConnectError("down"))],
    ids=["server_error", "unreachable"],
)
def test_a_failed_revoke_warns_but_still_deletes_the_tokens(
    swiggy: FakeSwiggyLogout, store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_swiggy(monkeypatch, swiggy)

    code, output = logout()

    assert (code, store.get(SWIGGY_TOKENS)) == (0, None)
    assert "Warning: Swiggy did not confirm the logout" in output


def test_the_client_registration_is_kept_so_the_next_login_can_reuse_it(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_swiggy(monkeypatch, FakeSwiggyLogout())

    logout()

    assert json.loads(store.get(SWIGGY_CLIENT) or "{}") == {"client_id": "client-1"}


def test_no_token_value_is_printed(
    store: InMemorySecretStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_swiggy(monkeypatch, FakeSwiggyLogout(status=500))

    _, output = logout()

    assert "access-1" not in output
    assert "refresh-1" not in output
