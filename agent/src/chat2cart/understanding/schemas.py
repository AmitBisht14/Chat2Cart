from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IntentLabel = Literal["order", "general", "mixed", "unsure"]
Unit = Literal["g", "kg", "ml", "l", "piece", "dozen", "pack"]
Substitute = Literal["never", "same_brand", "any"]


class Intent(BaseModel):
    """What a message is. order_text is the grocery part, set only for order and mixed."""

    label: IntentLabel
    order_text: str | None = None


class ExtractedItem(BaseModel):
    """One grocery item as asked for. Quantity and unit are empty when the message gives none."""

    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: Unit | None = None
    sources: list[str] = Field(default_factory=list)


class Extraction(BaseModel):
    """The only thing the model may return from an order message: a list of items."""

    model_config = ConfigDict(extra="forbid")

    items: list[ExtractedItem]


class SkippedItem(BaseModel):
    """An item left out of the cart, with the reason why. When in doubt, leave it out."""

    name: str
    reason: str
    sources: list[str] = Field(default_factory=list)


class PreferencedItem(BaseModel):
    """An extracted item with the rule book's brand, size and substitution rule attached."""

    name: str
    quantity: Decimal = Field(gt=0)
    unit: Unit | None
    brands: list[str]
    size: str | None
    substitute: Substitute
    sources: list[str] = Field(default_factory=list)


class ResolvedItem(BaseModel):
    """An item matched to exactly one Instamart variant, with the number of packs to add."""

    name: str
    spin_id: str
    sku_id: str
    variant_name: str
    quantity: int = Field(ge=1)
    sources: list[str] = Field(default_factory=list)
