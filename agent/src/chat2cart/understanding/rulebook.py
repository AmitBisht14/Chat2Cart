import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SIZE_PATTERN = re.compile(r"\d+(\.\d+)?\s*(g|kg|ml|l|pcs|pack|dozen)", re.IGNORECASE)
BULLET_PATTERN = re.compile(r"[-*]\s+(.*)")
HEADING_PATTERN = re.compile(r"##(?:\s+(.*))?")
KEY_TO_FIELD = {
    "aliases": "aliases",
    "brand": "brands",
    "default_quantity": "default_quantity",
    "min_quantity": "min_quantity",
    "size": "size",
    "substitute": "substitute",
}
LIST_FIELDS = frozenset({"aliases", "brands"})
CACHE_SIZE = 8


class RuleBookError(Exception):
    """The rule book is missing or has invalid entries. `errors` lists each as 'line N: ...'."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class RuleEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    aliases: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    default_quantity: int | None = Field(default=None, ge=1)
    min_quantity: int | None = Field(default=None, ge=1)
    size: str | None = None
    substitute: Literal["never", "same_brand", "any"] = "never"


def normalise_name(name: str) -> str:
    return " ".join(name.lower().split())


def parse_rulebook(text: str) -> dict[str, RuleEntry]:
    """Parse the markdown rule book into entries keyed by normalised name and by each alias.

    Raises one RuleBookError listing every problem with its line number.
    """
    errors: list[str] = []
    entries: list[RuleEntry] = []
    section: _Section | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        heading = HEADING_PATTERN.fullmatch(stripped)
        if heading:
            _close(section, entries, errors)
            section = _Section(number, (heading.group(1) or "").strip())
        elif section is None and BULLET_PATTERN.fullmatch(stripped):
            errors.append(f"line {number}: this bullet comes before any '## Item' heading")
        elif section is not None and BULLET_PATTERN.fullmatch(stripped):
            _add_bullet(section, number, stripped, errors)
    _close(section, entries, errors)
    index = _index(entries, errors)
    if errors:
        raise RuleBookError(errors)
    return index


def load_rulebook(path: Path) -> dict[str, RuleEntry]:
    """Load the rule book, re-parsing only when the file has changed since the last call."""
    try:
        stat = path.stat()
    except OSError:
        raise RuleBookError(
            [f"Rule book not found at {path}. Copy rulebook.example.md to start one."]
        ) from None
    return _parse_file(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=CACHE_SIZE)
def _parse_file(path: Path, _mtime_ns: int, _size: int) -> dict[str, RuleEntry]:
    # The mtime and size are part of the cache key only: an edited file is a new key.
    return parse_rulebook(path.read_text(encoding="utf-8"))


class _Section:
    def __init__(self, line: int, name: str) -> None:
        self.line = line
        self.name = name
        self.values: dict[str, str | list[str]] = {}
        self.value_lines: dict[str, int] = {}


def _add_bullet(section: _Section, number: int, stripped: str, errors: list[str]) -> None:
    bullet = BULLET_PATTERN.fullmatch(stripped)
    content = bullet.group(1) if bullet else ""
    key, separator, value = content.partition(":")
    field = KEY_TO_FIELD.get(key.strip().lower())
    if not separator:
        errors.append(f"line {number}: expected 'key: value'")
    elif field is None:
        errors.append(f"line {number}: unknown key '{key.strip()}'")
    else:
        section.values[field] = _split(value) if field in LIST_FIELDS else value.strip()
        section.value_lines[field] = number


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _close(section: _Section | None, entries: list[RuleEntry], errors: list[str]) -> None:
    if section is None:
        return
    if not section.name:
        errors.append(f"line {section.line}: the '##' heading has no item name")
        return
    try:
        entries.append(RuleEntry.model_validate({"name": section.name, **section.values}))
    except ValidationError as error:
        errors.extend(_field_errors(section, error))
        return
    entry = entries[-1]
    if entry.size is not None and not SIZE_PATTERN.fullmatch(entry.size):
        line = section.value_lines["size"]
        errors.append(f"line {line}: size '{entry.size}' should look like '500 g' or '30 pcs'")


def _field_errors(section: _Section, error: ValidationError) -> list[str]:
    messages = []
    for detail in error.errors():
        field = str(detail["loc"][0])
        line = section.value_lines.get(field, section.line)
        messages.append(f"line {line}: {field}: {detail['msg']}")
    return messages


def _index(entries: list[RuleEntry], errors: list[str]) -> dict[str, RuleEntry]:
    index: dict[str, RuleEntry] = {}
    for entry in entries:
        for label in [entry.name, *entry.aliases]:
            key = normalise_name(label)
            if key in index and index[key] is not entry:
                errors.append(f"'{label}' is used by both '{index[key].name}' and '{entry.name}'")
            index[key] = entry
    return index
