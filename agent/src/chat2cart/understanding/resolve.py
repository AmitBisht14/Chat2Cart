from decimal import Decimal

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.products import Product, Variant, search
from chat2cart.understanding.dedupe import dedupe_by_variant
from chat2cart.understanding.hints import load_hints
from chat2cart.understanding.packsize import amount_of, pack_count, parse_amount
from chat2cart.understanding.schemas import PreferencedItem, ResolvedItem, SkippedItem

NO_MATCH = "no_match"
OUT_OF_STOCK = "out_of_stock"
AMBIGUOUS = "ambiguous"
INEXACT_CONVERSION = "inexact_conversion"


async def resolve_items(
    items: list[PreferencedItem], client: SwiggyClient, address_id: str
) -> tuple[list[ResolvedItem], list[SkippedItem]]:
    """Match each item to exactly one in-stock variant, or skip it with a reason.

    Search is read-only. When in doubt the item is skipped: the cart never gets a guess. The
    user's go-to items and recent orders are read once and only break ties.
    """
    hints = await load_hints(client, address_id)
    resolved: list[ResolvedItem] = []
    skipped: list[SkippedItem] = []
    for item in items:
        products = await search(client, item.name, address_id)
        outcome = choose_variant(item, products, hints)
        if isinstance(outcome, ResolvedItem):
            resolved.append(outcome)
        else:
            skipped.append(outcome)
    return dedupe_by_variant(resolved), skipped


def choose_variant(
    item: PreferencedItem, products: list[Product], hints: set[str]
) -> ResolvedItem | SkippedItem:
    variants = _unique_variants(products)
    candidates = _select(item, [variant for variant in variants if variant.in_stock])
    if not candidates:
        return _skip(item, _why_none(item, variants))
    counted = _with_pack_counts(item, candidates)
    if not counted:
        return _skip(item, INEXACT_CONVERSION)
    if len(counted) > 1:
        return _break_tie(item, counted, hints)
    return _resolved(item, *counted[0])


def _break_tie(
    item: PreferencedItem, counted: list[tuple[Variant, int]], hints: set[str]
) -> ResolvedItem | SkippedItem:
    """Several variants already fit the message and rule book. Exactly one hinted one decides."""
    hinted = [(variant, count) for variant, count in counted if variant.spin_id in hints]
    if len(hinted) == 1:
        return _resolved(item, *hinted[0])
    return _skip(item, AMBIGUOUS)


def _resolved(item: PreferencedItem, variant: Variant, count: int) -> ResolvedItem:
    return ResolvedItem(
        name=item.name,
        spin_id=variant.spin_id,
        sku_id=variant.sku_id,
        variant_name=variant.name,
        quantity=count,
        sources=item.sources,
    )


def _unique_variants(products: list[Product]) -> list[Variant]:
    seen: set[tuple[str, str]] = set()
    unique: list[Variant] = []
    for product in products:
        for variant in product.variants:
            if (variant.spin_id, variant.sku_id) not in seen:
                seen.add((variant.spin_id, variant.sku_id))
                unique.append(variant)
    return unique


def _select(item: PreferencedItem, pool: list[Variant]) -> list[Variant]:
    """The variants that fit the rule book's brand and size, then its substitution rule."""
    sized = _with_size(item.size, pool)
    if not item.brands:
        return sized
    preferred = _first_preferred_brand(item.brands, sized)
    if preferred:
        return preferred
    if item.substitute == "same_brand":
        return _first_preferred_brand(item.brands, pool)
    if item.substitute == "any":
        return sized
    return []


def _with_size(size: str | None, pool: list[Variant]) -> list[Variant]:
    if size is None:
        return pool
    wanted = parse_amount(size)
    return [variant for variant in pool if parse_amount(variant.pack_size) == wanted]


def _first_preferred_brand(brands: list[str], pool: list[Variant]) -> list[Variant]:
    for brand in brands:
        matching = [variant for variant in pool if _same_brand(variant.brand, brand)]
        if matching:
            return matching
    return []


def _same_brand(first: str, second: str) -> bool:
    return " ".join(first.lower().split()) == " ".join(second.lower().split())


def _why_none(item: PreferencedItem, variants: list[Variant]) -> str:
    """Nothing in stock fits. It is out_of_stock if something that fits exists, else no_match."""
    return OUT_OF_STOCK if _select(item, variants) else NO_MATCH


def _with_pack_counts(
    item: PreferencedItem, candidates: list[Variant]
) -> list[tuple[Variant, int]]:
    requested = amount_of(item.quantity, item.unit)
    if requested is None:
        return _counted_as_packs(item.quantity, candidates)
    counted: list[tuple[Variant, int]] = []
    for variant in candidates:
        pack = parse_amount(variant.pack_size)
        count = None if pack is None else pack_count(requested, pack)
        if count is not None:
            counted.append((variant, count))
    return counted


def _counted_as_packs(quantity: Decimal, candidates: list[Variant]) -> list[tuple[Variant, int]]:
    """With no weight or volume unit the quantity already is a pack count, if it is whole."""
    if quantity != quantity.to_integral_value():
        return []
    return [(variant, int(quantity)) for variant in candidates]


def _skip(item: PreferencedItem, reason: str) -> SkippedItem:
    return SkippedItem(name=item.name, reason=reason)
