from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import BadInputError, SwiggyError


class CartItem(BaseModel):
    """One cart line. requested_quantity is set only on reduced items: what was asked for."""

    model_config = ConfigDict(populate_by_name=True)

    spin_id: str = Field(alias="spinId")
    sku_id: str = Field(alias="skuId")
    name: str
    quantity: int
    requested_quantity: int | None = Field(default=None, alias="requestedQuantity")


class Cart(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[CartItem]
    bill_total: Decimal = Field(alias="billTotal")


class CartWriteResult(BaseModel):
    """What Swiggy changed while writing: out-of-stock items it dropped, quantities it capped."""

    model_config = ConfigDict(populate_by_name=True)

    removed: list[CartItem] = Field(default_factory=list, alias="removedOutOfStockItems")
    reduced: list[CartItem] = Field(default_factory=list, alias="reducedQuantityItems")


async def read_cart(client: SwiggyClient) -> Cart:
    payload = await client.call_tool("get_cart")
    try:
        return Cart.model_validate(payload)
    except ValidationError:
        # Dropped on purpose: pydantic's message would echo the cart.
        raise SwiggyError("Swiggy's cart was not in the expected format.") from None


async def write_cart(
    client: SwiggyClient, items: list[CartItem], address_id: str
) -> CartWriteResult:
    """Replaces the ENTIRE Instamart cart with `items`; anything not listed is removed.

    Pass the complete list you want, including lines already in the cart. An empty list is
    refused: this module never empties a cart.
    """
    if not items:
        raise BadInputError("write_cart needs at least one item: it never empties the cart.")
    payload = await client.call_tool(
        "update_cart",
        {"selectedAddressId": address_id, "items": [_cart_line(item) for item in items]},
    )
    try:
        return CartWriteResult.model_validate(payload)
    except ValidationError:
        raise SwiggyError(
            "Swiggy updated the cart, but its answer was not in the expected format. "
            "Read the cart to see the result."
        ) from None


def _cart_line(item: CartItem) -> dict[str, object]:
    return {"spinId": item.spin_id, "skuId": item.sku_id, "quantity": item.quantity}
