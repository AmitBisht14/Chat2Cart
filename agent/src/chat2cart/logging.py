import logging
import re
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler

import structlog
from structlog.typing import EventDict, WrappedLogger

from chat2cart.config import Settings

LOGGER_NAME = "chat2cart"
LOG_FILE_NAME = "agent.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
DEFAULT_RUN_ID = "-"
REDACTED = "[redacted]"
SECRET_KEYS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "otp",
        "code_verifier",
        "session_key",
    }
)
BEARER_PATTERN = re.compile(r"Bearer\s+[\w.~+/=-]+", re.IGNORECASE)


def configure_logging(settings: Settings) -> None:
    """Write JSON lines to <data_dir>/logs/agent.log. Bind a run with bind_contextvars(run_id=)."""
    _attach_rotating_file_handler(settings)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_default_run_id,
            structlog.processors.TimeStamper(fmt="iso", key="ts"),
            structlog.stdlib.add_log_level,
            redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )


def redact_secrets(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    return redact_mapping(event_dict)


def redact_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): REDACTED if str(key).lower() in SECRET_KEYS else redact_value(item)
        for key, item in mapping.items()
    }


def redact_value(value: object) -> object:
    if isinstance(value, str):
        return BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list | tuple):
        return [redact_value(item) for item in value]
    return value


def _attach_rotating_file_handler(settings: Settings) -> None:
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    logger = logging.getLogger(LOGGER_NAME)
    for previous in list(logger.handlers):
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.getLevelNamesMapping()[settings.log_level])
    logger.propagate = False


def _add_default_run_id(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    event_dict.setdefault("run_id", DEFAULT_RUN_ID)
    return event_dict
