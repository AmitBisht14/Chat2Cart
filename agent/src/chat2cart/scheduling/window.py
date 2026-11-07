"""The ordering window.

Orders are built only inside the window, in the configured time zone (Asia/Kolkata by default),
never in the Mac's own time zone. Both ends are inclusive: with a 07:00 to 22:30 window, 07:00:00
and 22:30:00 are inside, 06:59:59 and anything after 22:30:00 is outside. A window never crosses
midnight (the configuration requires the start to be before the end).
"""

from datetime import datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo


class OrderingWindow(Protocol):
    """The settings the window check reads. `Settings` has all three."""

    @property
    def window_start(self) -> time: ...

    @property
    def window_end(self) -> time: ...

    @property
    def timezone(self) -> str: ...


def is_within_window(instant: datetime, window: OrderingWindow) -> bool:
    """Whether an instant falls inside the ordering window. Pass an aware datetime, such as
    datetime.now(UTC); a naive one is refused so the host's time zone can never leak in."""
    if instant.tzinfo is None:
        raise ValueError("is_within_window needs a timezone-aware datetime, such as one in UTC.")
    local = instant.astimezone(ZoneInfo(window.timezone)).time()
    return window.window_start <= local <= window.window_end
