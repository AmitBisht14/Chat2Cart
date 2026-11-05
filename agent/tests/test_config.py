from datetime import time
from pathlib import Path

import pytest

from chat2cart.config import load_settings


def test_valid_env_gives_typed_settings_with_defaults(valid_env: dict[str, str]) -> None:
    settings = load_settings(env_file=None)

    assert settings.sender_phone == "919876543210"
    assert settings.window_start == time(7, 0)
    assert settings.window_end == time(22, 30)
    assert settings.timezone == "Asia/Kolkata"
    assert settings.log_level == "INFO"
    assert settings.default_address_id is None
    assert settings.db_path == Path("data/chat2cart.sqlite")


def test_settings_are_read_from_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHAT2CART_SENDER_PHONE=919876543210\n"
        "CHAT2CART_RULEBOOK_PATH=rulebook.md\n"
        "CHAT2CART_DATA_DIR=data\n"
        "CHAT2CART_DB_PATH=data/db.sqlite\n"
        "CHAT2CART_WA_SESSION_DIR=wa-session\n"
    )

    settings = load_settings(env_file=env_file)

    assert settings.db_path == Path("data/db.sqlite")


@pytest.mark.parametrize(
    "missing",
    ["SENDER_PHONE", "RULEBOOK_PATH", "DATA_DIR", "DB_PATH"],
)
def test_missing_required_setting_names_the_variable(
    missing: str,
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(f"CHAT2CART_{missing}")

    with pytest.raises(SystemExit) as exit_info:
        load_settings(env_file=None)

    assert exit_info.value.code == 2
    assert f"CHAT2CART_{missing}: " in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TIMEZONE", "Mars/Olympus"),
        ("LOG_LEVEL", "LOUD"),
        ("SENDER_PHONE", "12345"),
        ("WINDOW_START", "not-a-time"),
    ],
)
def test_invalid_value_is_rejected_naming_the_variable(
    name: str,
    value: str,
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(f"CHAT2CART_{name}", value)

    with pytest.raises(SystemExit) as exit_info:
        load_settings(env_file=None)

    assert exit_info.value.code == 2
    assert f"CHAT2CART_{name}: " in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["+91 98765-43210", "0091 9876543210", "919876543210"])
def test_phone_is_normalised_to_digits_with_country_code(
    raw: str, valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHAT2CART_SENDER_PHONE", raw)

    assert load_settings(env_file=None).sender_phone == "919876543210"
