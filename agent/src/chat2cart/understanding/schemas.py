from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IntentLabel = Literal["order", "general", "mixed", "unsure"]
Unit = Literal["g", "kg", "ml", "l", "piece", "dozen", "pack"]


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


class Extraction(BaseModel):
    """The only thing the model may return from an order message: a list of items."""

    model_config = ConfigDict(extra="forbid")

    items: list[ExtractedItem]
