from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError

PAGE_SIZE = 10
MAX_PAGES = 20


@dataclass(frozen=True)
class Address:
    id: str
    description: str


@dataclass(frozen=True)
class AddressPage:
    addresses: list[Address]
    has_more: bool | None


class _RawAddress(BaseModel):
    id: str
    address_line: str = Field(default="", alias="addressLine")
    address_tag: str = Field(default="", alias="addressTag")


class _RawPagination(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    has_more: bool = Field(alias="hasMore")


class _RawPage(BaseModel):
    addresses: list[_RawAddress]
    pagination: _RawPagination | None = None


async def list_addresses(client: SwiggyClient) -> list[Address]:
    """All saved addresses, page by page. Only the get_addresses tool is called."""
    found: dict[str, Address] = {}
    for page_number in range(1, MAX_PAGES + 1):
        page = parse_page(await client.call_tool("get_addresses", {"page": page_number}))
        new_addresses = [address for address in page.addresses if address.id not in found]
        found.update({address.id: address for address in new_addresses})
        # A page with nothing new means the server ignored the page number; stop instead of looping.
        if not new_addresses or len(page.addresses) < PAGE_SIZE or page.has_more is False:
            break
    return list(found.values())


def parse_page(payload: dict[str, object]) -> AddressPage:
    try:
        raw = _RawPage.model_validate(payload)
    except ValidationError:
        # Dropped on purpose: the message would echo the addresses.
        raise SwiggyError("Swiggy's address list was not in the expected format.") from None
    has_more = raw.pagination.has_more if raw.pagination else None
    return AddressPage([_to_address(item) for item in raw.addresses], has_more)


def _to_address(item: _RawAddress) -> Address:
    # The phone number and category are left out: the list is only for telling addresses apart.
    parts = [text for text in (item.address_tag, item.address_line) if text]
    return Address(id=item.id, description=" | ".join(parts) or item.id)
