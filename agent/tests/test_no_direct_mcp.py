from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "chat2cart"
CLIENT_FILE = SOURCE_ROOT / "swiggy" / "client.py"


def source_files() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def test_only_the_swiggy_client_uses_the_mcp_sdk_client_or_names_the_server() -> None:
    offenders = [
        path.relative_to(SOURCE_ROOT)
        for path in source_files()
        if path != CLIENT_FILE
        and any(
            marker in path.read_text(encoding="utf-8")
            for marker in ("mcp.client", "mcp.swiggy.com/im")
        )
    ]

    assert offenders == []


def test_swiggy_tools_are_never_bound_to_a_model() -> None:
    offenders = [
        path.relative_to(SOURCE_ROOT)
        for path in source_files()
        if "bind_tools" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
