import subprocess
from typing import Any

import pytest
import structlog

from chat2cart.config import load_settings
from chat2cart.notify.base import Channel, NotifyKind, notifier_for, notify
from chat2cart.notify.channels import notify_from_settings
from chat2cart.notify.log_channel import LogChannel
from chat2cart.notify.macos import MacosChannel, send_macos


class RecordingRun:
    """Stands in for subprocess.run, so no test ever runs the real osascript."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._error = error

    def __call__(self, args: list[str], **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> RecordingRun:
    recorder = RecordingRun()
    monkeypatch.setattr("chat2cart.notify.macos.subprocess.run", recorder)
    return recorder


def test_macos_passes_the_title_and_body_as_arguments_to_osascript(run: RecordingRun) -> None:
    send_macos("Cart ready", "3 items added")

    ((args, kwargs),) = run.calls
    assert args[0] == "osascript"
    assert args[-2:] == ["Cart ready", "3 items added"]
    assert (kwargs["timeout"], kwargs["check"]) == (5, True)
    assert "shell" not in kwargs


def test_text_with_quotes_and_backslashes_is_passed_untouched(run: RecordingRun) -> None:
    send_macos('say "hi" \\ it\'s', "line one\nline two")

    ((args, _),) = run.calls
    assert args[-2:] == ['say "hi" \\ it\'s', "line one\nline two"]


def test_the_macos_channel_prefixes_the_kind_to_the_title(run: RecordingRun) -> None:
    assert notify(MacosChannel(), "alert", "WhatsApp logged out", "Run chat2cart-wa login") is True

    ((args, _),) = run.calls
    assert args[-2:] == ["Chat2Cart alert: WhatsApp logged out", "Run chat2cart-wa login"]


def test_the_log_channel_does_not_call_osascript(run: RecordingRun) -> None:
    assert notify(LogChannel(), "summary", "Cart ready", "3 items") is True

    assert run.calls == []


@pytest.mark.parametrize("kind", ["summary", "alert"])
def test_summary_and_alert_kinds_are_accepted(kind: NotifyKind, run: RecordingRun) -> None:
    assert notify(MacosChannel(), kind, "Title", "Body") is True


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired("osascript", 5),
        FileNotFoundError("osascript"),
        subprocess.CalledProcessError(1, "osascript"),
    ],
    ids=["timeout", "no_osascript", "non_zero_exit"],
)
def test_a_failure_never_raises_and_reports_false(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingRun(error)
    monkeypatch.setattr("chat2cart.notify.macos.subprocess.run", recorder)

    assert notify(MacosChannel(), "alert", "Title", "Body") is False
    assert len(recorder.calls) == 1


def test_a_channel_that_raises_anything_is_still_contained() -> None:
    class Broken:
        def send(self, kind: NotifyKind, title: str, body: str) -> None:
            raise RuntimeError("boom")

    assert notify(Broken(), "summary", "Title", "Body") is False


def test_the_sent_log_has_the_kind_and_title_but_never_the_body() -> None:
    with structlog.testing.capture_logs() as logs:
        notify(LogChannel(), "summary", "Cart ready", "2 kg atta for Amit")

    assert logs == [
        {"event": "notify.sent", "kind": "summary", "title": "Cart ready", "log_level": "info"}
    ]


def test_a_failure_is_logged_with_its_type_and_not_the_body() -> None:
    class Broken:
        def send(self, kind: NotifyKind, title: str, body: str) -> None:
            raise TimeoutError("slow")

    with structlog.testing.capture_logs() as logs:
        notify(Broken(), "alert", "Title", "secret body")

    assert logs == [
        {
            "event": "notify.failed",
            "kind": "alert",
            "title": "Title",
            "error_type": "TimeoutError",
            "log_level": "warning",
        }
    ]


def test_the_notifier_sends_through_the_channel_it_was_bound_to() -> None:
    sent: list[tuple[str, str, str]] = []

    class Recording:
        def send(self, kind: NotifyKind, title: str, body: str) -> None:
            sent.append((kind, title, body))

    channel: Channel = Recording()

    assert notifier_for(channel)("alert", "T", "B") is True
    assert sent == [("alert", "T", "B")]


def test_the_default_channel_is_macos(valid_env: dict[str, str]) -> None:
    assert load_settings(env_file=None).notify_channel == "macos"


def test_the_active_channel_is_chosen_in_config(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, run: RecordingRun
) -> None:
    monkeypatch.setenv("CHAT2CART_NOTIFY_CHANNEL", "log")

    sent = notify_from_settings(load_settings(env_file=None))("summary", "T", "B")

    assert (sent, run.calls) == (True, [])


def test_the_macos_channel_is_used_when_config_says_macos(
    valid_env: dict[str, str], run: RecordingRun
) -> None:
    notify_from_settings(load_settings(env_file=None))("summary", "T", "B")

    assert len(run.calls) == 1


def test_an_unknown_channel_is_rejected_naming_the_variable(
    valid_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CHAT2CART_NOTIFY_CHANNEL", "telegram")

    with pytest.raises(SystemExit):
        load_settings(env_file=None)

    assert "CHAT2CART_NOTIFY_CHANNEL: " in capsys.readouterr().err
