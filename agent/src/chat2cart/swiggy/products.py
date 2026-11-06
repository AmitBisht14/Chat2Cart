from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError


class Variant(BaseModel):
    """One purchasable pack of a product. The IDs are strings exactly as Swiggy returns them."""

    model_config = ConfigDict(populate_by_name=True)

    spin_id: str = Field(alias="spinId")
    sku_id: str = Field(alias="skuId")
    name: str
    brand: str
    pack_size: str = Field(alias="packSize")
    price: Decimal
    in_stock: bool = Field(alias="inStock")


class Product(BaseModel):
    name: str
    brand: str
    variants: list[Variant]


class _SearchResult(BaseModel):
    products: list[Product]


async def search(client: SwiggyClient, query: str, address_id: str) -> list[Product]:
    """Search Instamart for the address. Out-of-stock variants are kept, marked in_stock=False."""
    payload = await client.call_tool("search_products", {"addressId": address_id, "query": query})
    try:
        return _SearchResult.model_validate(payload).products
    except ValidationError:
        # Dropped on purpose: pydantic's message would echo the response.
        raise SwiggyError("Swiggy's product search was not in the expected format.") from None
