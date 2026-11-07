import os
from pathlib import Path

import pytest

from chat2cart.understanding.rulebook import (
    RuleBookError,
    RuleEntry,
    load_rulebook,
    normalise_name,
    parse_rulebook,
)

EXAMPLE_RULEBOOK = Path(__file__).parents[3] / "rulebook.example.md"


def test_the_committed_example_parses_and_eggs_has_every_field() -> None:
    entries = parse_rulebook(EXAMPLE_RULEBOOK.read_text(encoding="utf-8"))

    assert entries["eggs"] == RuleEntry(
        name="Eggs",
        aliases=["egg", "ande", "anda"],
        brands=["Farm Fresh", "Country Eggs"],
        default_quantity=1,
        min_quantity=1,
        size="30 pcs",
        substitute="same_brand",
    )


def test_an_alias_maps_to_the_same_entry_as_the_item_name() -> None:
    entries = parse_rulebook(EXAMPLE_RULEBOOK.read_text(encoding="utf-8"))

    assert entries["ande"] is entries["eggs"]
    assert {"milk", "doodh", "atta", "onions", "pyaaz"} <= entries.keys()


def test_an_entry_with_no_keys_gets_the_defaults() -> None:
    (entry,) = {entry.name: entry for entry in parse_rulebook("## Bread\n").values()}.values()

    assert entry == RuleEntry(name="Bread")
    assert (entry.default_quantity, entry.substitute) == (None, "never")


def test_notes_and_the_title_are_ignored() -> None:
    entries = parse_rulebook(
        "# Title\n\nSome note about eggs.\n\n## Eggs\nanother note\n- size: 6 pcs\n"
    )

    assert entries["eggs"].size == "6 pcs"


def test_an_invalid_file_reports_every_problem_with_its_line_number() -> None:
    text = (
        "- stray: bullet\n"  # line 1
        "## Eggs\n"  # line 2
        "- colour: brown\n"  # line 3
        "- default_quantity: lots\n"  # line 4
        "- size: huge\n"  # line 5
        "- no colon here\n"  # line 6
        "- substitute: sometimes\n"  # line 7
    )

    with pytest.raises(RuleBookError) as error_info:
        parse_rulebook(text)

    errors = error_info.value.errors
    assert errors[0] == "line 1: this bullet comes before any '## Item' heading"
    assert "line 3: unknown key 'colour'" in errors
    assert "line 6: expected 'key: value'" in errors
    assert any(error.startswith("line 4: default_quantity:") for error in errors)
    assert any(error.startswith("line 7: substitute:") for error in errors)


def test_a_size_that_does_not_look_like_a_size_is_reported_on_its_line() -> None:
    with pytest.raises(RuleBookError) as error_info:
        parse_rulebook("## Eggs\n- size: huge\n")

    assert error_info.value.errors == ["line 2: size 'huge' should look like '500 g' or '30 pcs'"]


@pytest.mark.parametrize("quantity", ["0", "-3", "2.5"])
def test_a_quantity_must_be_a_whole_number_of_at_least_one(quantity: str) -> None:
    with pytest.raises(RuleBookError, match="line 2: default_quantity"):
        parse_rulebook(f"## Eggs\n- default_quantity: {quantity}\n")


def test_two_entries_cannot_claim_the_same_name() -> None:
    with pytest.raises(RuleBookError, match="'ande' is used by both 'Eggs' and 'Anda'"):
        parse_rulebook("## Eggs\n- aliases: ande\n## Anda\n- aliases: ande\n")


def test_a_heading_with_no_name_is_reported() -> None:
    with pytest.raises(RuleBookError, match="line 1: the '##' heading has no item name"):
        parse_rulebook("## \n")


def test_names_are_matched_ignoring_case_and_extra_spaces() -> None:
    assert normalise_name("  Toned   MILK ") == "toned milk"
    assert "toned milk" in parse_rulebook("## Toned  Milk\n")


def test_load_rulebook_picks_up_an_edited_file_without_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "rulebook.md"
    path.write_text("## Eggs\n- default_quantity: 30\n", encoding="utf-8")
    assert load_rulebook(path)["eggs"].default_quantity == 30

    path.write_text("## Eggs\n- default_quantity: 12\n", encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))

    assert load_rulebook(path)["eggs"].default_quantity == 12


def test_load_rulebook_does_not_parse_again_when_the_file_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "rulebook.md"
    path.write_text("## Eggs\n", encoding="utf-8")

    assert load_rulebook(path) is load_rulebook(path)


def test_a_missing_rule_book_is_a_rule_book_error_that_names_the_example(tmp_path: Path) -> None:
    with pytest.raises(RuleBookError, match="rulebook.example.md"):
        load_rulebook(tmp_path / "nope.md")
