from decimal import Decimal

from chat2cart.understanding.dedupe import dedupe_by_name, dedupe_by_variant
from chat2cart.understanding.schemas import ExtractedItem, ResolvedItem


def extracted(
    name: str, quantity: str | None = None, unit: str | None = None, source: str = "m1"
) -> ExtractedItem:
    return ExtractedItem.model_validate(
        {
            "name": name,
            "quantity": None if quantity is None else Decimal(quantity),
            "unit": unit,
            "sources": [source],
        }
    )


def resolved(name: str, spin_id: str, quantity: int = 1, source: str = "m1") -> ResolvedItem:
    return ResolvedItem(
        name=name,
        spin_id=spin_id,
        sku_id=f"sku-{spin_id}",
        variant_name=name,
        quantity=quantity,
        sources=[source],
    )


def test_names_that_differ_only_by_case_and_spaces_become_one_item() -> None:
    items = dedupe_by_name([extracted(" Milk "), extracted("milk"), extracted("MILK  ")])

    assert len(items) == 1
    assert items[0].name.strip().lower() == "milk"


def test_the_same_item_twice_with_no_quantity_stays_one_item_with_no_quantity() -> None:
    (item,) = dedupe_by_name([extracted("milk"), extracted("milk", source="m2")])

    assert (item.quantity, item.unit) == (None, None)


def test_two_stated_quantities_in_the_same_unit_keep_the_larger_and_both_sources() -> None:
    (item,) = dedupe_by_name(
        [extracted("milk", "2", source="m1"), extracted("milk", "3", source="m2")]
    )

    assert (item.quantity, item.sources) == (Decimal("3"), ["m1", "m2"])


def test_the_larger_quantity_wins_whichever_message_came_first() -> None:
    (item,) = dedupe_by_name(
        [extracted("milk", "5", source="m1"), extracted("milk", "3", source="m2")]
    )

    assert item.quantity == Decimal("5")


def test_quantities_are_never_added_together() -> None:
    (item,) = dedupe_by_name([extracted("milk", "2"), extracted("milk", "2", source="m2")])

    assert item.quantity == Decimal("2")


def test_when_only_one_item_has_a_quantity_that_quantity_and_unit_are_used() -> None:
    (item,) = dedupe_by_name([extracted("milk"), extracted("milk", "2", "l", source="m2")])

    assert (item.quantity, item.unit) == (Decimal("2"), "l")


def test_quantities_in_different_units_keep_the_first() -> None:
    (item,) = dedupe_by_name([extracted("atta", "1", "kg"), extracted("atta", "500", "g", "m2")])

    assert (item.quantity, item.unit) == (Decimal("1"), "kg")


def test_sources_are_joined_without_duplicates() -> None:
    (item,) = dedupe_by_name(
        [
            extracted("milk", source="m1"),
            extracted("milk", source="m1"),
            extracted("milk", source="m2"),
        ]
    )

    assert item.sources == ["m1", "m2"]


def test_different_items_stay_separate_in_order_of_first_appearance() -> None:
    items = dedupe_by_name([extracted("eggs"), extracted("milk"), extracted("Eggs", "6")])

    assert [item.name for item in items] == ["eggs", "milk"]


def test_two_names_resolved_to_the_same_variant_become_one_line() -> None:
    items = dedupe_by_variant(
        [resolved("ande", "EGG-12", source="m1"), resolved("eggs", "EGG-12", source="m2")]
    )

    assert [(item.spin_id, item.sources) for item in items] == [("EGG-12", ["m1", "m2"])]


def test_different_variants_stay_separate() -> None:
    items = dedupe_by_variant([resolved("eggs", "EGG-6"), resolved("eggs", "EGG-12")])

    assert [item.spin_id for item in items] == ["EGG-6", "EGG-12"]


def test_the_same_variant_keeps_the_larger_pack_count_not_the_sum() -> None:
    (item,) = dedupe_by_variant(
        [
            resolved("eggs", "EGG-12", 2),
            resolved("ande", "EGG-12", 3, "m2"),
            resolved("e", "EGG-12", 1, "m3"),
        ]
    )

    assert item.quantity == 3
