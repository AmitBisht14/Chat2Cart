from datetime import UTC, datetime
from pathlib import Path

import pytest

from chat2cart.app import main
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.db.repos import enqueue_request
from chat2cart.understanding.schemas import ExtractedItem

EXAMPLE_RULEBOOK = Path(__file__).parents[2] / "rulebook.example.md"


@pytest.fixture
def started_env(valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CHAT2CART_DB_PATH", str(tmp_path / "data" / "chat2cart.sqlite"))
    rulebook = tmp_path / "rulebook.md"
    rulebook.write_text(EXAMPLE_RULEBOOK.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("CHAT2CART_RULEBOOK_PATH", str(rulebook))
    return rulebook


def test_main_creates_and_migrates_the_database(started_env: Path, tmp_path: Path) -> None:
    main().stop()

    db_path = tmp_path / "data" / "chat2cart.sqlite"
    version = connect(db_path).execute("SELECT version FROM schema_meta").fetchone()[0]
    assert version == 1


def test_main_starts_the_cart_worker(started_env: Path) -> None:
    worker = main()
    try:
        assert worker.is_alive()
    finally:
        worker.stop()


def test_main_fails_fast_with_line_numbers_on_an_invalid_rule_book(
    started_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    started_env.write_text("## Eggs\n- colour: brown\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    assert "line 2: unknown key 'colour'" in capsys.readouterr().err


def test_main_fails_fast_when_the_rule_book_is_missing(
    started_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    started_env.unlink()

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    assert "Rule book not found" in capsys.readouterr().err


def test_main_releases_a_queue_missed_overnight_when_it_starts_inside_the_window(
    started_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "data" / "chat2cart.sqlite"
    with connect(db_path) as conn:
        migrate(conn)
        enqueue_request(conn, "m1", [ExtractedItem(name="atta")])
    monkeypatch.setattr("chat2cart.app._now", lambda: datetime(2026, 11, 7, 4, 30, tzinfo=UTC))

    service = main()
    service.stop()

    with connect(db_path) as reader:
        statuses = [row["status"] for row in reader.execute("SELECT status FROM request_queue")]
        sources = [row["source"] for row in reader.execute("SELECT source FROM cart_jobs")]
    assert (statuses, sources) == (["released"], ["overnight_batch"])


def test_main_starts_the_release_scheduler(started_env: Path) -> None:
    service = main()
    try:
        assert service.is_alive()
    finally:
        service.stop()
