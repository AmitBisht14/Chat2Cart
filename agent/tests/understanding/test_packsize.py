from decimal import Decimal

import pytest

from chat2cart.understanding.packsize import Amount, amount_of, pack_count, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500 g", Amount(Decimal("500"), "mass")),
        ("1 kg", Amount(Decimal("1000"), "mass")),
        ("1.5 l", Amount(Decimal("1500"), "volume")),
        ("500ML", Amount(Decimal("500"), "volume")),
        ("30 pcs", Amount(Decimal("30"), "count")),
        ("1 dozen", Amount(Decimal("12"), "count")),
    ],
)
def test_a_pack_size_is_read_into_base_units(text: str, expected: Amount) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["Pack of 2", "2 x 500 g", "", "large", "500"])
def test_a_pack_size_that_is_not_a_plain_amount_is_not_read(text: str) -> None:
    assert parse_amount(text) is None


@pytest.mark.parametrize("unit", [None, "pack", "bunch"])
def test_no_unit_pack_or_unknown_unit_gives_no_amount(unit: str | None) -> None:
    assert amount_of(Decimal("2"), unit) is None


@pytest.mark.parametrize(
    ("requested", "pack", "expected"),
    [
        (Amount(Decimal("2000"), "mass"), Amount(Decimal("1000"), "mass"), 2),
        (Amount(Decimal("1500"), "mass"), Amount(Decimal("1000"), "mass"), None),
        (Amount(Decimal("500"), "mass"), Amount(Decimal("1000"), "mass"), None),
        (Amount(Decimal("1000"), "mass"), Amount(Decimal("1000"), "volume"), None),
    ],
)
def test_a_pack_count_is_given_only_when_the_amounts_divide_exactly(
    requested: Amount, pack: Amount, expected: int | None
) -> None:
    assert pack_count(requested, pack) == expected
