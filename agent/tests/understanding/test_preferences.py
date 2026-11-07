from decimal import Decimal

import pytest

from chat2cart.understanding.preferences import apply_preferences
from chat2cart.understanding.rulebook import parse_rulebook
from chat2cart.understanding.schemas import ExtractedItem, PreferencedItem, SkippedItem

RULEBOOK = parse_rulebook(
    """\
## Eggs
- aliases: ande
- brand: Farm Fresh, Country Eggs
- default_quantity: 30
- min_quantity: 6
- size: 30 pcs
- substitute: same_brand

## Milk
- default_quantity: 2
- min_quantity: 4

## Bread
"""
)


def item(name: str, quantity: str | None = None, unit: str | None = None) -> ExtractedItem:
    return ExtractedItem.model_validate(
        {"name": name, "quantity": None if quantity is None else Decimal(quantity), "unit": unit}
    )


def preferenced(name: str, quantity: str | None = None, unit: str | None = None) -> PreferencedItem:
    (result,), _ = apply_preferences([item(name, quantity, unit)], RULEBOOK)
    return result


def test_a_quantity_in_the_message_overrides_the_default() -> None:
    assert preferenced("eggs", "12").quantity == Decimal("12")


def test_the_default_quantity_is_used_when_the_message_gives_none() -> None:
    assert preferenced("eggs").quantity == Decimal("30")


def test_a_default_below_the_minimum_is_raised_to_the_minimum() -> None:
    assert preferenced("milk").quantity == Decimal("4")


def test_an_entry_with_no_default_orders_one() -> None:
    assert preferenced("bread").quantity == Decimal("1")


def test_a_message_quantity_below_the_minimum_still_wins() -> None:
    assert preferenced("eggs", "2").quantity == Decimal("2")


def test_brands_size_and_substitution_rule_are_attached() -> None:
    result = preferenced("eggs", "12")

    assert result == PreferencedItem(
        name="eggs",
        quantity=Decimal("12"),
        unit=None,
        brands=["Farm Fresh", "Country Eggs"],
        size="30 pcs",
        substitute="same_brand",
    )


def test_an_entry_with_no_keys_attaches_no_preferences_and_never_substitutes() -> None:
    result = preferenced("bread")

    assert (result.brands, result.size, result.substitute) == ([], None, "never")


@pytest.mark.parametrize("written", ["Ande", "  ANDE ", "eggs", "Eggs"])
def test_an_item_is_matched_to_its_rule_by_name_or_alias_ignoring_case_and_spaces(
    written: str,
) -> None:
    assert preferenced(written).size == "30 pcs"


def test_the_unit_from_the_message_is_kept_with_the_message_quantity() -> None:
    assert preferenced("milk", "2", "l").unit == "l"


def test_a_unit_without_a_quantity_is_dropped_because_the_default_is_not_in_that_unit() -> None:
    result = preferenced("milk", None, "l")

    assert (result.quantity, result.unit) == (Decimal("4"), None)


def test_an_item_with_no_rule_is_skipped_with_the_reason_no_rule() -> None:
    items, skipped = apply_preferences([item("dragonfruit", "1")], RULEBOOK)

    assert (items, skipped) == ([], [SkippedItem(name="dragonfruit", reason="no_rule")])


def test_matched_and_unmatched_items_are_split_in_order() -> None:
    items, skipped = apply_preferences(
        [item("eggs"), item("dragonfruit"), item("milk"), item("kiwi")], RULEBOOK
    )

    assert [entry.name for entry in items] == ["eggs", "milk"]
    assert [entry.name for entry in skipped] == ["dragonfruit", "kiwi"]
