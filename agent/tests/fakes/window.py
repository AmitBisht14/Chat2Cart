from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class Window:
    """An ordering window for tests: 07:00 to 22:30 in Asia/Kolkata unless changed."""

    window_start: time = time(7, 0)
    window_end: time = time(22, 30)
    timezone: str = "Asia/Kolkata"
