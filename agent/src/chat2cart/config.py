import re
from datetime import time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import typer
from pydantic import BeforeValidator, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "CHAT2CART_"
DEFAULT_ADDRESS_ENV = f"{ENV_PREFIX}DEFAULT_ADDRESS_ID"
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
CONFIG_ERROR_EXIT_CODE = 2
MIN_PHONE_DIGITS = 11
MAX_PHONE_DIGITS = 15


def normalize_phone(raw: str) -> str:
    """Keep digits only, drop a leading + or 00, and require a country code (11 to 15 digits)."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise ValueError(
            f"phone number must have {MIN_PHONE_DIGITS} to {MAX_PHONE_DIGITS} digits "
            "including the country code"
        )
    return digits


PhoneNumber = Annotated[str, BeforeValidator(lambda value: normalize_phone(str(value)))]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_ignore_empty=True,
        extra="ignore",
    )

    sender_phone: PhoneNumber
    window_start: time = time(7, 0)
    window_end: time = time(22, 30)
    timezone: str = "Asia/Kolkata"
    default_address_id: str | None = None
    rulebook_path: Path
    data_dir: Path
    db_path: Path
    llm_provider: str
    llm_model: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError(f"unknown time zone '{value}'") from error
        return value


def load_settings(env_file: Path | None = ENV_FILE) -> Settings:
    try:
        # _env_file works at runtime; pydantic's dataclass transform hides it from mypy.
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as error:
        for line in format_config_errors(error):
            typer.echo(line, err=True)
        raise SystemExit(CONFIG_ERROR_EXIT_CODE) from None


def format_config_errors(error: ValidationError) -> list[str]:
    return [
        f"{ENV_PREFIX}{'.'.join(str(part) for part in detail['loc']).upper()}: {detail['msg']}"
        for detail in error.errors()
    ]


def save_env_value(path: Path, key: str, value: str) -> None:
    """Set key=value in an env file: replace the existing line or append one. Other lines stay."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    new_line = f"{key}={_env_text(value)}"
    if any(_env_key(line) == key for line in lines):
        lines = [new_line if _env_key(line) == key else line for line in lines]
    else:
        lines.append(new_line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_key(line: str) -> str:
    return line.split("=", 1)[0].strip()


def _env_text(value: str) -> str:
    if re.fullmatch(r"[\w.:@/+-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
