from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError

PAGE_SIZE = 10
MAX_PAGES = 20
ID_KEYS = ("addressId", "id")


@dataclass(frozen=True)
class Address:
    id: str
    description: str


@dataclass(frozen=True)
class AddressPage:
    addresses: list[Address]
    has_next_page: bool | None


class _RawPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    addresses: list[dict[str, object]]
    has_next_page: bool | None = Field(default=None, alias="hasNextPage")


async def list_addresses(client: SwiggyClient) -> list[Address]:
    """All saved addresses, page by page. Only the get_addresses tool is called."""
    found: dict[str, Address] = {}
    for page_number in range(1, MAX_PAGES + 1):
        page = parse_page(await client.call_tool("get_addresses", {"page": page_number}))
        new_addresses = [address for address in page.addresses if address.id not in found]
        found.update({address.id: address for address in new_addresses})
        # A page with nothing new means the server ignored the page number; stop instead of looping.
        if not new_addresses or len(page.addresses) < PAGE_SIZE or page.has_next_page is False:
            break
    return list(found.values())


def parse_page(payload: dict[str, object]) -> AddressPage:
    data = payload.get("data")
    container = data if isinstance(data, dict) else payload
    try:
        raw = _RawPage.model_validate(container)
    except ValidationError:
        # Dropped on purpose: the message would echo the addresses.
        raise SwiggyError("Swiggy's address list was not in the expected format.") from None
    return AddressPage([_to_address(item) for item in raw.addresses], raw.has_next_page)


def _to_address(item: dict[str, object]) -> Address:
    address_id = next((str(item[key]) for key in ID_KEYS if item.get(key)), None)
    if address_id is None:
        raise SwiggyError("A saved address in Swiggy's response has no ID.")
    parts = [value for key, value in item.items() if key not in ID_KEYS and _is_text(value)]
    return Address(id=address_id, description=" | ".join(map(str, parts)) or address_id)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)
