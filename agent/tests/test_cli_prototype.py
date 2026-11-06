from pathlib import Path

import pytest
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, use_fake_swiggy
from typer.testing import CliRunner

from chat2cart.cli import app

ADDRESS_ID = "addr-002"
SEARCH = load_swiggy_fixture("search_products_milk")
CART = load_swiggy_fixture("get_cart_two_items")
UPDATED_CART = {**CART, "billTotal": 120.5}
WRITE_OK = load_swiggy_fixture("update_cart_ok")

# Menu order from the search fixture: 1 Toned 500 ml, 2 Toned 1 l, 3 Toned 2 l (out of stock),
# 4 Full Cream 500 ml, 5 Slim 1 l. The cart fixture already holds variant 1 (x2) and variant 4 (x1).


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> None:
    monkeypatch.setenv("CHAT2CART_DEFAULT_ADDRESS_ID", ADDRESS_ID)


ADDED_SLIM_MILK = [
    {"spinId": "0A1B2C3D", "skuId": "000123456", "quantity": 2},
    {"spinId": "0B2C3D4E", "skuId": "000987654", "quantity": 1},
    {"spinId": "0C3D4E5F", "skuId": "000555001", "quantity": 1},
]


def written_items(transport: FakeSwiggyTransport) -> object:
    return transport.calls[2].arguments["items"]


def run_prototype(
    monkeypatch: pytest.MonkeyPatch, transport: FakeSwiggyTransport, *args: str, answers: str = ""
) -> tuple[int, str]:
    use_fake_swiggy(monkeypatch, transport)
    result = CliRunner().invoke(app, ["prototype", "milk", *args], input=answers)
    return result.exit_code, result.output


def full_run() -> FakeSwiggyTransport:
    return FakeSwiggyTransport(SEARCH, CART, WRITE_OK, UPDATED_CART)


def test_dry_run_only_searches_and_leaves_the_cart_alone(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeSwiggyTransport(SEARCH)

    code, output = run_prototype(monkeypatch, transport, "--dry-run")

    assert code == 0
    assert "Dry run: cart not changed" in output
    assert "1. Toned Milk | 500 ml | Rs 29 | in stock" in output
    assert "3. Toned Milk | 2 l | Rs 108 | OUT OF STOCK" in output
    assert [call.name for call in transport.calls] == ["search_products"]


def test_existing_cart_lines_are_kept_and_the_new_variant_is_added(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = full_run()

    code, _ = run_prototype(monkeypatch, transport, answers="5\n")

    assert code == 0
    assert transport.calls[2].arguments["selectedAddressId"] == ADDRESS_ID
    assert written_items(transport) == ADDED_SLIM_MILK


def test_a_variant_already_in_the_cart_gets_one_more_not_a_second_line(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = full_run()

    run_prototype(monkeypatch, transport, answers="1\n")

    assert written_items(transport) == [
        {"spinId": "0A1B2C3D", "skuId": "000123456", "quantity": 3},
        {"spinId": "0B2C3D4E", "skuId": "000987654", "quantity": 1},
    ]


def test_an_out_of_stock_variant_is_refused_and_asked_again(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = full_run()

    code, output = run_prototype(monkeypatch, transport, answers="3\n5\n")

    assert code == 0
    assert "That variant is out of stock" in output
    assert written_items(transport) == ADDED_SLIM_MILK


def test_the_cart_is_read_back_and_printed_with_the_total_and_a_reminder(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = run_prototype(monkeypatch, full_run(), answers="5\n")

    assert code == 0
    assert "Example Dairy Toned Milk 500 ml x 2" in output
    assert "Total: Rs 120.5" in output
    assert "This tool never checks out" in output


def test_only_allowed_tools_are_called_in_this_exact_order(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = full_run()

    run_prototype(monkeypatch, transport, answers="5\n")

    assert [call.name for call in transport.calls] == [
        "search_products",
        "get_cart",
        "update_cart",
        "get_cart",
    ]


def test_without_a_chosen_address_it_asks_for_one_and_calls_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valid_env: dict[str, str]
) -> None:
    monkeypatch.setattr("chat2cart.cli.ENV_FILE", tmp_path / "missing.env")
    transport = FakeSwiggyTransport(SEARCH)

    code, output = run_prototype(monkeypatch, transport)

    assert code == 2
    assert "Run `chat2cart swiggy address` first" in output
    assert transport.calls == []
