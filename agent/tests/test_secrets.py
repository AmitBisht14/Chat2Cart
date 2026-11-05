import keyring
import pytest
from keyring.errors import KeyringError

from chat2cart.secrets import InMemorySecretStore, KeychainSecretStore, SecretStoreError


def test_in_memory_store_sets_gets_and_deletes() -> None:
    store = InMemorySecretStore()

    store.set("llm.api_key", "sk-test-123")
    stored = store.get("llm.api_key")
    store.delete("llm.api_key")

    assert stored == "sk-test-123"
    assert store.get("llm.api_key") is None


def test_keychain_store_uses_the_chat2cart_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        keyring, "set_password", lambda service, key, value: calls.append((service, key, value))
    )
    monkeypatch.setattr(keyring, "get_password", lambda service, key: f"{service}/{key}")

    KeychainSecretStore().set("llm.api_key", "sk-test-123")

    assert calls == [("chat2cart", "llm.api_key", "sk-test-123")]
    assert KeychainSecretStore().get("llm.api_key") == "chat2cart/llm.api_key"


def test_keychain_error_message_names_the_key_but_not_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_set_password(service: str, key: str, value: str) -> None:
        raise KeyringError(f"backend rejected {value}")

    monkeypatch.setattr(keyring, "set_password", failing_set_password)

    with pytest.raises(SecretStoreError) as error_info:
        KeychainSecretStore().set("llm.api_key", "sk-test-123")

    assert "llm.api_key" in str(error_info.value)
    assert "sk-test-123" not in str(error_info.value)
    assert error_info.value.__cause__ is None
    assert error_info.value.__suppress_context__


def test_real_keychain_is_blocked_in_tests() -> None:
    with pytest.raises(SecretStoreError):
        KeychainSecretStore().set("llm.api_key", "sk-test-123")
