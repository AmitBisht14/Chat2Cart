import os
from collections.abc import Iterator

import pytest

VALID_ENV = {
    "CHAT2CART_SENDER_PHONE": "919876543210",
    "CHAT2CART_RULEBOOK_PATH": "rulebook.md",
    "CHAT2CART_DATA_DIR": "data",
    "CHAT2CART_DB_PATH": "data/chat2cart.sqlite",
}


@pytest.fixture(autouse=True)
def clean_chat2cart_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in [name for name in os.environ if name.startswith("CHAT2CART_")]:
        monkeypatch.delenv(name)
    yield


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    return dict(VALID_ENV)
