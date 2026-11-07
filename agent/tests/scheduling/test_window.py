import os
import time as host_time
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fakes.window import Window

from chat2cart.config import load_settings
from chat2cart.scheduling.window import is_within_window

IST = ZoneInfo("Asia/Kolkata")


def ist(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, 7, hour, minute, second, tzinfo=IST)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (ist(6, 59), False),
        (ist(6, 59, 59), False),
        (ist(7, 0), True),
        (ist(12, 0), True),
        (ist(22, 30), True),
        (ist(22, 30, 1), False),
        (ist(22, 31), False),
        (ist(0, 0), False),
    ],
    ids=["06:59", "06:59:59", "07:00", "12:00", "22:30", "22:30:01", "22:31", "00:00"],
)
def test_boundaries_in_india_standard_time(instant: datetime, expected: bool) -> None:
    assert is_within_window(instant, Window()) is expected


def test_the_configured_window_is_used_not_a_fixed_one() -> None:
    window = Window(window_start=time(8, 0), window_end=time(20, 0))

    assert [is_within_window(ist(h, 0), window) for h in (7, 8, 20, 21)] == [
        False,
        True,
        True,
        False,
    ]


def test_an_instant_in_utc_is_judged_in_the_configured_zone() -> None:
    assert is_within_window(datetime(2026, 11, 7, 1, 30, tzinfo=UTC), Window()) is True
    assert is_within_window(datetime(2026, 11, 7, 1, 29, tzinfo=UTC), Window()) is False


def test_an_instant_in_any_other_zone_is_converted_before_it_is_compared() -> None:
    new_york = timezone(timedelta(hours=-5))

    assert is_within_window(datetime(2026, 11, 6, 20, 30, tzinfo=new_york), Window()) is True


def test_the_zone_comes_from_the_configuration() -> None:
    window = Window(timezone="America/New_York")

    # New York is UTC-5 on this date: 12:00 UTC is 07:00 there, 11:59 UTC is 06:59.
    assert is_within_window(datetime(2026, 11, 7, 12, 0, tzinfo=UTC), window) is True
    assert is_within_window(datetime(2026, 11, 7, 11, 59, tzinfo=UTC), window) is False


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_within_window(datetime(2026, 11, 7, 12, 0), Window())


@pytest.fixture
def host_zone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "America/New_York")
    host_time.tzset()
    yield
    monkeypatch.undo()
    host_time.tzset()


def test_the_hosts_time_zone_has_no_effect(host_zone: None) -> None:
    assert os.environ["TZ"] == "America/New_York"
    results = [
        is_within_window(i, Window()) for i in (ist(6, 59), ist(7, 0), ist(22, 30), ist(22, 31))
    ]

    assert results == [False, True, True, False]


def test_the_default_settings_describe_the_7_to_22_30_window_in_kolkata(
    valid_env: dict[str, str],
) -> None:
    settings = load_settings(env_file=None)

    assert is_within_window(ist(7, 0), settings) is True
    assert is_within_window(ist(22, 31), settings) is False
