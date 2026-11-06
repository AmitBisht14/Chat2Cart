from decimal import Decimal

from pydantic import AliasPath, BaseModel, ConfigDict, Field, ValidationError

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError


class Variant(BaseModel):
    """One purchasable pack of a product. The IDs are strings exactly as Swiggy returns them."""

    model_config = ConfigDict(populate_by_name=True)

    spin_id: str = Field(alias="spinId")
    sku_id: str = Field(alias="skuId")
    name: str = Field(alias="displayName")
    brand: str = Field(alias="brandName")
    pack_size: str = Field(alias="quantityDescription")
    price: Decimal = Field(validation_alias=AliasPath("price", "offerPrice"))
    in_stock: bool = Field(alias="isInStockAndAvailable")


class Product(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(alias="displayName")
    brand: str
    variants: list[Variant] = Field(alias="variations")


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
