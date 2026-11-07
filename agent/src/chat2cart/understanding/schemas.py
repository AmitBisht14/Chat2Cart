from typing import Literal

from pydantic import BaseModel

IntentLabel = Literal["order", "general", "mixed", "unsure"]


class Intent(BaseModel):
    """What a message is. order_text is the grocery part, set only for order and mixed."""

    label: IntentLabel
    order_text: str | None = None
