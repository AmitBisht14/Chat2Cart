import logging
import os
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
import structlog
from keyring.backends import fail

from chat2cart.logging import LOGGER_NAME

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
def valid_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    env = {**VALID_ENV, "CHAT2CART_DATA_DIR": str(tmp_path / "data")}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


@pytest.fixture(autouse=True)
def block_real_keychain() -> Iterator[None]:
    previous = keyring.get_keyring()
    # keyring ships fail.Keyring without type hints.
    keyring.set_keyring(fail.Keyring())  # type: ignore[no-untyped-call]
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
