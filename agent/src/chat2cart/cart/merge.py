from dataclasses import dataclass
from decimal import Decimal

import structlog

from chat2cart.swiggy.cart import CartItem, ReducedItem, read_cart, write_cart
from chat2cart.swiggy.client import SwiggyClient
from chat2cart.understanding.schemas import ResolvedItem


@dataclass(frozen=True)
class CartDiff:
    """A variant whose quantity in the cart read back differs from the intended one."""

    spin_id: str
    intended: int | None
    actual: int | None


@dataclass(frozen=True)
class MergeResult:
    """What the merge meant to leave in the cart, what Swiggy then held, and any difference.

    actual is None when nothing was written (a dry run, or nothing new to add).
    """

    intended: list[CartItem]
    actual: list[CartItem] | None
    removed: list[CartItem]
    reduced: list[ReducedItem]
    diffs: list[CartDiff]
    bill_total: Decimal


async def merge_into_cart(
    client: SwiggyClient,
    address_id: str,
    new_items: list[ResolvedItem],
    dry_run: bool = False,
) -> MergeResult:
    """Add new items to the existing cart without losing anything already in it.

    update_cart replaces the whole cart, so this reads the cart, keeps every line (hand-added ones
    included), adds the new items, writes the full list in one call, then reads the cart back and
    reports any difference. With dry_run, or with nothing new to add, nothing is written.
    """
    cart = await read_cart(client)
    intended = merge_lines(cart.items, new_items)
    if dry_run or not new_items:
        return MergeResult(intended, None, [], [], [], cart.bill_total)
    written = await write_cart(client, intended, address_id)
    read_back = await read_cart(client)
    result = MergeResult(
        intended=intended,
        actual=read_back.items,
        removed=written.removed,
        reduced=written.reduced,
        diffs=find_diffs(intended, read_back.items),
        bill_total=read_back.bill_total,
    )
    _log_merge(result)
    return result


def merge_lines(existing: list[CartItem], new_items: list[ResolvedItem]) -> list[CartItem]:
    """Every existing line, then the new items. A variant already there keeps the larger quantity.

    The larger quantity, not the sum, so a job that is retried never doubles an item.
    """
    lines = {item.spin_id: item for item in existing}
    for new in new_items:
        current = lines.get(new.spin_id)
        if current is None:
            lines[new.spin_id] = _cart_line(new)
        elif new.quantity > current.quantity:
            lines[new.spin_id] = current.model_copy(update={"quantity": new.quantity})
    return list(lines.values())


def find_diffs(intended: list[CartItem], actual: list[CartItem]) -> list[CartDiff]:
    """Every variant that is missing, changed or unexpected in the cart read back."""
    wanted = {item.spin_id: item.quantity for item in intended}
    found = {item.spin_id: item.quantity for item in actual}
    return [
        CartDiff(spin_id, wanted.get(spin_id), found.get(spin_id))
        for spin_id in [*wanted, *(spin_id for spin_id in found if spin_id not in wanted)]
        if wanted.get(spin_id) != found.get(spin_id)
    ]


def _cart_line(item: ResolvedItem) -> CartItem:
    return CartItem.model_validate(
        {
            "spin_id": item.spin_id,
            "sku_id": item.sku_id,
            "name": item.variant_name,
            "quantity": item.quantity,
        }
    )


def _log_merge(result: MergeResult) -> None:
    structlog.get_logger().info(
        "cart_merged",
        lines=len(result.intended),
        diffs=len(result.diffs),
        removed=len(result.removed),
        reduced=len(result.reduced),
    )
