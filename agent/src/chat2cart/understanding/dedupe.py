from collections.abc import Callable
from functools import reduce

from chat2cart.understanding.rulebook import normalise_name
from chat2cart.understanding.schemas import ExtractedItem, ResolvedItem


def dedupe_by_name(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Merge items whose normalised names are equal, before any product matching."""
    return _merge_groups(items, lambda item: normalise_name(item.name), _merge_extracted)


def dedupe_by_variant(items: list[ResolvedItem]) -> list[ResolvedItem]:
    """Merge resolved items that picked the same variant, so a product never appears twice."""
    return _merge_groups(items, lambda item: item.spin_id, _merge_resolved)


def _merge_groups[ItemT](
    items: list[ItemT], key: Callable[[ItemT], str], merge: Callable[[ItemT, ItemT], ItemT]
) -> list[ItemT]:
    """Group by key in order of first appearance and merge each group into one item."""
    groups: dict[str, list[ItemT]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return [reduce(merge, group) for group in groups.values()]


def _merge_extracted(first: ExtractedItem, second: ExtractedItem) -> ExtractedItem:
    """Duplicates are never summed: repeated reminders must not inflate the order. The name of the
    first appearance is kept.

    One stated quantity is used as it is. Two in the same unit keep the larger. Two in different
    units keep the first.
    """
    keep = _item_to_keep(first, second)
    return keep.model_copy(
        update={"name": first.name, "sources": _joined(first.sources, second.sources)}
    )


def _item_to_keep(first: ExtractedItem, second: ExtractedItem) -> ExtractedItem:
    if first.quantity is None:
        return second if second.quantity is not None else first
    if second.quantity is None or second.unit != first.unit:
        return first
    return second if second.quantity > first.quantity else first


def _merge_resolved(first: ResolvedItem, second: ResolvedItem) -> ResolvedItem:
    """The same variant twice keeps the larger pack count, never the sum."""
    keep = second if second.quantity > first.quantity else first
    return keep.model_copy(
        update={"name": first.name, "sources": _joined(first.sources, second.sources)}
    )


def _joined(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))
