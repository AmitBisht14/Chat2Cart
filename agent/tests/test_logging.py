import json
from pathlib import Path

import pytest
import structlog

from chat2cart.config import load_settings
from chat2cart.logging import LOGGER_NAME, configure_logging, redact_value


def read_log_lines(data_dir: Path) -> list[str]:
    return (data_dir / "logs" / "agent.log").read_text(encoding="utf-8").splitlines()


def test_log_entry_has_timestamp_level_run_id_and_event(valid_env: dict[str, str]) -> None:
    settings = load_settings(env_file=None)
    configure_logging(settings)

    structlog.get_logger(LOGGER_NAME).info("cart_updated", items=2)

    entry = json.loads(read_log_lines(settings.data_dir)[0])
    assert entry["event"] == "cart_updated"
    assert entry["level"] == "info"
    assert entry["run_id"] == "-"
    assert entry["ts"]


def test_bound_run_id_is_written(valid_env: dict[str, str]) -> None:
    settings = load_settings(env_file=None)
    configure_logging(settings)
    structlog.contextvars.bind_contextvars(run_id="run-1")

    structlog.get_logger(LOGGER_NAME).info("run_started")

    assert json.loads(read_log_lines(settings.data_dir)[0])["run_id"] == "run-1"


def test_bearer_token_is_never_written(valid_env: dict[str, str]) -> None:
    settings = load_settings(env_file=None)
    configure_logging(settings)

    structlog.get_logger(LOGGER_NAME).info(
        "called with Bearer abc.def",
        headers={"Authorization": "Bearer abc.def"},
        detail="retry using Bearer abc.def now",
    )

    written = "\n".join(read_log_lines(settings.data_dir))
    assert "abc.def" not in written
    assert "[redacted]" in written


def test_secret_fields_are_redacted_at_any_depth_and_case() -> None:
    redacted = redact_value({"data": {"Refresh_Token": "x", "items": [{"OTP": "123456"}]}})

    assert redacted == {"data": {"Refresh_Token": "[redacted]", "items": [{"OTP": "[redacted]"}]}}


def test_log_file_rotates_by_size(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chat2cart.logging.LOG_MAX_BYTES", 200)
    settings = load_settings(env_file=None)
    configure_logging(settings)

    for number in range(20):
        structlog.get_logger(LOGGER_NAME).info("filler_entry", number=number)

    assert (settings.data_dir / "logs" / "agent.log.1").exists()
