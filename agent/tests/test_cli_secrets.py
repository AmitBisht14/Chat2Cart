import pytest
from typer.testing import CliRunner

from chat2cart.cli import app
from chat2cart.secrets import InMemorySecretStore


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> InMemorySecretStore:
    in_memory = InMemorySecretStore()
    monkeypatch.setattr("chat2cart.cli.build_secret_store", lambda: in_memory)
    return in_memory


def test_secrets_set_stores_the_key_without_echoing_it(store: InMemorySecretStore) -> None:
    result = CliRunner().invoke(app, ["secrets", "set", "llm-api-key"], input="sk-test-123\n")

    assert result.exit_code == 0
    assert store.get("llm.api_key") == "sk-test-123"
    assert "sk-test-123" not in result.output
    assert "Saved llm-api-key to the Keychain." in result.output


def test_secrets_set_rejects_an_unknown_name_without_echoing_it(
    store: InMemorySecretStore,
) -> None:
    result = CliRunner().invoke(app, ["secrets", "set", "sk-typed-by-mistake"])

    assert result.exit_code == 2
    assert "sk-typed-by-mistake" not in result.output
