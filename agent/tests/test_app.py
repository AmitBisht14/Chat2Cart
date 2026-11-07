from pathlib import Path

import pytest

from chat2cart.app import main
from chat2cart.db.connection import connect


def test_main_creates_and_migrates_the_database(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "data" / "chat2cart.sqlite"
    monkeypatch.setenv("CHAT2CART_DB_PATH", str(db_path))

    main()

    version = connect(db_path).execute("SELECT version FROM schema_meta").fetchone()[0]
    assert version == 1
