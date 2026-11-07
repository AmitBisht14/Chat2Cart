from pathlib import Path

import pytest
from fakes.swiggy import FakeSwiggyTransport, load_swiggy_fixture, use_fake_swiggy
from typer.testing import CliRunner

from chat2cart.cli import app
from chat2cart.config import load_settings

ENV_CONTENT = (
    "CHAT2CART_SENDER_PHONE=919876543210\n"
    "CHAT2CART_RULEBOOK_PATH=rulebook.md\n"
    "CHAT2CART_DATA_DIR=data\n"
    "CHAT2CART_DB_PATH=data/chat2cart.sqlite\n"
    "CHAT2CART_LLM_PROVIDER=anthropic\n"
    "CHAT2CART_LLM_MODEL=test-model\n"
    "CHAT2CART_LOG_LEVEL=DEBUG\n"
)


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> Path:
    path = tmp_path / ".env"
    path.write_text(ENV_CONTENT, encoding="utf-8")
    monkeypatch.setattr("chat2cart.cli.ENV_FILE", path)
    return path


def test_all_addresses_across_pages_are_listed_and_the_choice_is_saved(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeSwiggyTransport(
        load_swiggy_fixture("get_addresses_page1"), load_swiggy_fixture("get_addresses_page2")
    )
    use_fake_swiggy(monkeypatch, transport)

    result = CliRunner().invoke(app, ["swiggy", "address"], input="2\n")

    assert result.exit_code == 0
    assert "1. " in result.output
    assert "13. Work | 13 Example Street, Bengaluru" in result.output
    assert [call.arguments for call in transport.calls] == [{"page": 1}, {"page": 2}]
    assert load_settings(env_file=env_file).default_address_id == "addr-002"
    assert env_file.read_text(encoding="utf-8").startswith(ENV_CONTENT)


def test_no_saved_address_explains_where_to_add_one(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_swiggy(monkeypatch, FakeSwiggyTransport(load_swiggy_fixture("get_addresses_empty")))

    result = CliRunner().invoke(app, ["swiggy", "address"])

    assert result.exit_code == 1
    assert "Add a delivery address in the Swiggy app" in result.output
    assert env_file.read_text(encoding="utf-8") == ENV_CONTENT


def test_only_the_get_addresses_tool_is_called(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeSwiggyTransport(load_swiggy_fixture("get_addresses_page2"))
    use_fake_swiggy(monkeypatch, transport)

    CliRunner().invoke(app, ["swiggy", "address"], input="1\n")

    assert {call.name for call in transport.calls} == {"get_addresses"}


def test_a_number_outside_the_list_is_asked_again(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_swiggy(monkeypatch, FakeSwiggyTransport(load_swiggy_fixture("get_addresses_page2")))

    result = CliRunner().invoke(app, ["swiggy", "address"], input="9\n3\n")

    assert result.exit_code == 0
    assert "Enter a number from 1 to 3." in result.output
    assert load_settings(env_file=env_file).default_address_id == "addr-013"


def test_not_logged_in_asks_for_a_login(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_swiggy(monkeypatch, FakeSwiggyTransport({}), logged_in=False)

    result = CliRunner().invoke(app, ["swiggy", "address"])

    assert result.exit_code == 1
    assert "Run chat2cart login swiggy" in result.output


def test_an_unexpected_response_is_reported_not_shown_as_no_addresses(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_swiggy(monkeypatch, FakeSwiggyTransport({"success": True, "data": {"places": []}}))

    result = CliRunner().invoke(app, ["swiggy", "address"])

    assert result.exit_code == 1
    assert "not in the expected format" in result.output
    assert "No saved addresses" not in result.output
