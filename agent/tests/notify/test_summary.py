from decimal import Decimal

import pytest

from chat2cart.cart.outcomes import CappedItem
from chat2cart.notify.summary import REMINDER, compose_summary
from chat2cart.pipeline.state import RunReport
from chat2cart.understanding.schemas import ResolvedItem, SkippedItem


def resolved(variant_name: str, quantity: int) -> ResolvedItem:
    return ResolvedItem(
        name="item", spin_id="S", sku_id="K", variant_name=variant_name, quantity=quantity
    )


def report(**changes: object) -> RunReport:
    fields: dict[str, object] = {
        "intent": "order",
        "dry_run": False,
        "added": [],
        "skipped": [],
        "removed": [],
        "reduced": [],
        "diffs": [],
        "total": Decimal("120"),
        "below_minimum": False,
        "sources": ["m1"],
    }
    return RunReport.model_validate({**fields, **changes})


def lines_of(text: str) -> list[str]:
    return text.splitlines()


def test_the_sections_appear_in_order_added_skipped_reduced_total() -> None:
    text = compose_summary(
        report(
            added=[resolved("Aashirvaad Atta 1 kg", 2), resolved("Amul Milk 500 ml", 1)],
            skipped=[SkippedItem(name="dragonfruit", reason="no_rule")],
            reduced=[CappedItem(name="Toned Milk", requested=99, applied=20)],
        )
    )

    assert lines_of(text)[:4] == [
        "Added: Aashirvaad Atta 1 kg x 2, Amul Milk 500 ml x 1",
        "Skipped: dragonfruit (no_rule)",
        "Reduced: Toned Milk 99->20",
        "Total: ₹120",
    ]


def test_a_skipped_item_shows_its_reason() -> None:
    text = compose_summary(
        report(
            skipped=[
                SkippedItem(name="eggs", reason="out_of_stock"),
                SkippedItem(name="atta", reason="ambiguous"),
            ]
        )
    )

    assert "Skipped: eggs (out_of_stock), atta (ambiguous)" in text


def test_a_skipped_item_with_no_reason_shows_unknown() -> None:
    text = compose_summary(report(skipped=[SkippedItem(name="eggs", reason="")]))

    assert "Skipped: eggs (unknown)" in text


def test_empty_sections_say_none() -> None:
    text = compose_summary(report())

    assert lines_of(text)[:3] == ["Added: none", "Skipped: none", "Reduced: none"]


def test_the_minimum_order_flag_shows_only_when_below_the_minimum() -> None:
    below = compose_summary(report(below_minimum=True, total=Decimal("98")))
    fine = compose_summary(report(below_minimum=False))

    assert "Below the ₹99 minimum order." in below
    assert "minimum" not in fine


@pytest.mark.parametrize("below", [True, False])
def test_the_reminder_is_always_the_last_line_even_when_every_section_is_empty(below: bool) -> None:
    text = compose_summary(report(below_minimum=below))

    assert lines_of(text)[-1] == REMINDER
    assert "Keep the Swiggy app closed" in REMINDER


def test_the_total_keeps_its_decimals() -> None:
    assert "Total: ₹93.50" in compose_summary(report(total=Decimal("93.50")))


def test_an_unknown_total_says_unknown() -> None:
    assert "Total: unknown" in compose_summary(report(total=None))
