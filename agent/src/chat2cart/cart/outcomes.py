from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from chat2cart.swiggy.cart import CartItem, ReducedItem
from chat2cart.swiggy.errors import DomainError, SwiggyError
from chat2cart.understanding.schemas import SkippedItem

MIN_ORDER_RUPEES = Decimal(99)
NOT_SERVICEABLE_REASON = "address_not_serviceable"
OUT_OF_STOCK = "out_of_stock"


class AddressNotServiceableError(SwiggyError):
    """Swiggy cannot serve the delivery address right now. The request is queued again."""


class CappedItem(BaseModel):
    """An item whose quantity Swiggy capped: what was asked for and what the cart got."""

    name: str
    reason: Literal["capped"] = "capped"
    requested: int
    applied: int


def is_below_minimum(total: Decimal | None) -> bool:
    """True when a cart that was written is under Swiggy's minimum order. It is still built."""
    return total is not None and total < MIN_ORDER_RUPEES


def is_not_serviceable(error: DomainError) -> bool:
    """Swiggy's code says so; the message is the fallback when a response has no code."""
    code = (error.code or "").upper()
    return "NOT_SERVICEABLE" in code or "not serviceable" in error.message.lower()


def out_of_stock_skips(removed: list[CartItem]) -> list[SkippedItem]:
    return [SkippedItem(name=item.name, reason=OUT_OF_STOCK) for item in removed]


def capped_items(reduced: list[ReducedItem]) -> list[CappedItem]:
    return [
        CappedItem(name=item.name, requested=item.requested_quantity, applied=item.capped_quantity)
        for item in reduced
    ]
