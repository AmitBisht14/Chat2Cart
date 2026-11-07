import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

AmountKind = Literal["mass", "volume", "count"]

# Each unit as (how many base units it holds, kind). Base units are g, ml and pieces.
UNITS: dict[str, tuple[int, AmountKind]] = {
    "g": (1, "mass"),
    "gm": (1, "mass"),
    "kg": (1000, "mass"),
    "ml": (1, "volume"),
    "l": (1000, "volume"),
    "ltr": (1000, "volume"),
    "pc": (1, "count"),
    "pcs": (1, "count"),
    "piece": (1, "count"),
    "pieces": (1, "count"),
    "dozen": (12, "count"),
}
PACK_SIZE_PATTERN = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([a-z]+)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Amount:
    """A weight, volume or count in base units (g, ml, pieces)."""

    value: Decimal
    kind: AmountKind


def parse_amount(text: str) -> Amount | None:
    """Read '500 g', '1.5 l' or '30 pcs'. Anything else, such as 'Pack of 2', gives None."""
    match = PACK_SIZE_PATTERN.fullmatch(text)
    return None if match is None else amount_of(Decimal(match.group(1)), match.group(2))


def amount_of(quantity: Decimal, unit: str | None) -> Amount | None:
    """The amount for a quantity and unit. None for no unit, 'pack' or an unknown unit."""
    known = UNITS.get((unit or "").lower())
    return None if known is None else Amount(quantity * known[0], known[1])


def pack_count(requested: Amount, pack: Amount) -> int | None:
    """How many packs make up the requested amount, or None unless that is an exact whole number."""
    if requested.kind != pack.kind or pack.value <= 0:
        return None
    count, remainder = divmod(requested.value, pack.value)
    return int(count) if remainder == 0 and count >= 1 else None
