import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "swiggy"


@dataclass(frozen=True)
class TransportCall:
    token: str
    name: str
    arguments: dict[str, object]


class FakeSwiggyTransport:
    """Scripted Swiggy transport. Each call returns or raises the next item; the last repeats."""

    def __init__(self, *script: dict[str, object] | Exception) -> None:
        self._script = script
        self.calls: list[TransportCall] = []

    async def __call__(
        self, token: str, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append(TransportCall(token, name, arguments))
        step = self._script[min(len(self.calls), len(self._script)) - 1]
        if isinstance(step, Exception):
            raise step
        return step


class RecordingSleep:
    """Replaces asyncio.sleep so retry tests never wait."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def load_swiggy_fixture(name: str) -> dict[str, object]:
    """A recorded (or hand-made) Swiggy response from tests/fixtures/swiggy/<name>.json."""
    loaded = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded
