import asyncio
from decimal import Decimal

import pytest
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, logged_in_client

from chat2cart.understanding.resolve import resolve_items
from chat2cart.understanding.schemas import PreferencedItem, ResolvedItem, SkippedItem

ADDRESS_ID = "addr-002"


def item(
    name: str,
    quantity: str = "1",
    unit: str | None = None,
    brands: list[str] | None = None,
    size: str | None = None,
    substitute: str = "never",
) -> PreferencedItem:
    return PreferencedItem.model_validate(
        {
            "name": name,
            "quantity": Decimal(quantity),
            "unit": unit,
            "brands": brands or [],
            "size": size,
            "substitute": substitute,
        }
    )


def resolve(
    fixture: str, wanted: PreferencedItem
) -> tuple[list[ResolvedItem], list[SkippedItem], FakeSwiggyTransport]:
    transport = FakeSwiggyTransport(load_swiggy_fixture(fixture))
    resolved, skipped = asyncio.run(
        resolve_items([wanted], logged_in_client(transport), ADDRESS_ID)
    )
    return resolved, skipped, transport


def reason_of(fixture: str, wanted: PreferencedItem) -> str:
    resolved, skipped, _ = resolve(fixture, wanted)
    assert resolved == []
    return skipped[0].reason


def test_a_single_match_keeps_the_ids_exactly_as_recorded() -> None:
    wanted = item("eggs", brands=["Farm Fresh"], size="30 pcs")

    resolved, skipped, _ = resolve("search_products_eggs", wanted)

    assert skipped == []
    assert resolved == [
        ResolvedItem(
            name="eggs",
            spin_id="EGG-FF-30",
            sku_id="SKU-FF-30",
            variant_name="Farm Fresh Eggs",
            quantity=1,
        )
    ]


def test_the_search_asks_for_the_item_name_and_the_address() -> None:
    _, _, transport = resolve(
        "search_products_eggs", item("eggs", size="6 pcs", brands=["Farm Fresh"])
    )

    assert [(call.name, call.arguments) for call in transport.calls] == [
        ("search_products", {"addressId": ADDRESS_ID, "query": "eggs"})
    ]


def test_several_matching_variants_give_ambiguous() -> None:
    assert reason_of("search_products_eggs", item("eggs")) == "ambiguous"


def test_the_first_preferred_brand_with_stock_wins_over_a_later_one() -> None:
    wanted = item("eggs", brands=["Country Eggs", "Farm Fresh"], size="12 pcs")

    resolved, _, _ = resolve("search_products_eggs", wanted)

    assert [r.spin_id for r in resolved] == ["EGG-CE-12"]


def test_no_variant_at_all_gives_no_match() -> None:
    assert reason_of("search_products_none", item("dragonfruit")) == "no_match"


def test_a_brand_that_is_not_sold_gives_no_match() -> None:
    wanted = item("eggs", brands=["Nobody Farms"], size="12 pcs")

    assert reason_of("search_products_eggs", wanted) == "no_match"


def test_an_out_of_stock_variant_is_never_chosen_and_never_substitutes_by_default() -> None:
    wanted = item("eggs", brands=["Country Eggs"], size="30 pcs")

    assert reason_of("search_products_eggs", wanted) == "out_of_stock"


def test_substitute_any_chooses_another_brand_when_the_preferred_one_is_out_of_stock() -> None:
    wanted = item("eggs", brands=["Country Eggs"], size="30 pcs", substitute="any")

    resolved, _, _ = resolve("search_products_eggs", wanted)

    assert [r.spin_id for r in resolved] == ["EGG-FF-30"]


def test_substitute_same_brand_chooses_another_size_of_that_brand_only() -> None:
    wanted = item("eggs", brands=["Country Eggs"], size="30 pcs", substitute="same_brand")

    resolved, _, _ = resolve("search_products_eggs", wanted)

    assert [r.spin_id for r in resolved] == ["EGG-CE-12"]


def test_same_brand_substitution_never_crosses_to_another_brand() -> None:
    wanted = item("atta", brands=["Sample Mills"], size="5 kg", substitute="same_brand")

    resolved, _, _ = resolve("search_products_atta", wanted)

    assert [r.spin_id for r in resolved] == ["ATTA-SM-1"]


@pytest.mark.parametrize(
    ("fixture", "brand", "quantity", "unit", "size", "expected"),
    [
        ("search_products_atta", "Aashirvaad", "2", "kg", "1 kg", 2),
        ("search_products_atta", "Aashirvaad", "5", "kg", "5 kg", 1),
        ("search_products_atta", "Aashirvaad", "3", "pack", "1 kg", 3),
        ("search_products_atta", "Aashirvaad", "3", None, "1 kg", 3),
        ("search_products_milk", "Example Dairy", "1500", "ml", "500 ml", 3),
        ("search_products_eggs", "Farm Fresh", "1", "dozen", "12 pcs", 1),
        ("search_products_eggs", "Farm Fresh", "24", "piece", "12 pcs", 2),
    ],
)
def test_an_exact_conversion_gives_the_pack_count(
    fixture: str, brand: str, quantity: str, unit: str | None, size: str, expected: int
) -> None:
    resolved, _, _ = resolve(fixture, item("x", quantity, unit, [brand], size))

    assert [r.quantity for r in resolved] == [expected]


def test_a_volume_converts_to_a_pack_count_of_the_wanted_size() -> None:
    wanted = item("milk", "1.5", "l", ["Example Dairy"], "500 ml")

    resolved, _, _ = resolve("search_products_milk", wanted)

    assert [(r.spin_id, r.quantity) for r in resolved] == [("0A1B2C3D", 3)]


def test_one_and_a_half_kg_against_a_1_kg_pack_is_inexact_and_skipped() -> None:
    wanted = item("atta", "1.5", "kg", ["Aashirvaad"], "1 kg")

    assert reason_of("search_products_atta", wanted) == "inexact_conversion"


def test_a_fractional_pack_count_with_no_unit_is_inexact_and_skipped() -> None:
    wanted = item("atta", "2.5", None, ["Aashirvaad"], "1 kg")

    assert reason_of("search_products_atta", wanted) == "inexact_conversion"


def test_a_weight_asked_of_volume_packs_is_inexact_and_skipped() -> None:
    wanted = item("milk", "1", "kg", ["Example Dairy"], "500 ml")

    assert reason_of("search_products_milk", wanted) == "inexact_conversion"


def test_conversion_without_a_size_rule_skips_when_several_pack_sizes_divide_exactly() -> None:
    wanted = item("atta", "5", "kg", ["Aashirvaad"])

    assert reason_of("search_products_atta", wanted) == "ambiguous"


def test_every_item_ends_with_exactly_one_variant_or_one_skip_reason() -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("search_products_eggs"),
        load_swiggy_fixture("search_products_none"),
        load_swiggy_fixture("search_products_atta"),
    )
    items = [
        item("eggs", brands=["Farm Fresh"], size="30 pcs"),
        item("dragonfruit"),
        item("atta", "2", "kg", ["Aashirvaad"], "1 kg"),
    ]

    resolved, skipped = asyncio.run(resolve_items(items, logged_in_client(transport), ADDRESS_ID))

    assert [r.name for r in resolved] == ["eggs", "atta"]
    assert [(s.name, s.reason) for s in skipped] == [("dragonfruit", "no_match")]
