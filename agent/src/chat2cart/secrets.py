from typing import Protocol

import keyring
from keyring.errors import KeyringError

KEYCHAIN_SERVICE = "chat2cart"
LLM_API_KEY = "llm.api_key"
SWIGGY_CLIENT = "swiggy.client"
SWIGGY_TOKENS = "swiggy.tokens"


class SecretStoreError(Exception):
    """A secret operation failed. The message names the key, never the value."""


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class InMemorySecretStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._secrets.get(key)

    def set(self, key: str, value: str) -> None:
        self._secrets[key] = value

    def delete(self, key: str) -> None:
        if key not in self._secrets:
            raise SecretStoreError(f"Could not delete secret '{key}': not found")
        del self._secrets[key]


class KeychainSecretStore:
    def get(self, key: str) -> str | None:
        try:
            return keyring.get_password(KEYCHAIN_SERVICE, key)
        except KeyringError:
            raise SecretStoreError(f"Could not read secret '{key}' from the Keychain") from None

    def set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(KEYCHAIN_SERVICE, key, value)
        except KeyringError:
            raise SecretStoreError(f"Could not write secret '{key}' to the Keychain") from None

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, key)
        except KeyringError:
            raise SecretStoreError(f"Could not delete secret '{key}' from the Keychain") from None
