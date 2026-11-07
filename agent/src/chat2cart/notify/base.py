from collections.abc import Callable
from typing import Literal, Protocol

import structlog

NotifyKind = Literal["summary", "alert"]
Notify = Callable[[NotifyKind, str, str], bool]


class Channel(Protocol):
    """Where summaries and alerts go. Add a new channel as a new implementation of this."""

    def send(self, kind: NotifyKind, title: str, body: str) -> None: ...


def notify(channel: Channel, kind: NotifyKind, title: str, body: str) -> bool:
    """Send a summary or an alert. Returns whether it was sent; it never raises.

    Callers are the order pipeline and the alert code, and a notification problem must never stop
    them, so every error is logged and turned into False. Only the kind and title are logged,
    never the body, which can name items.
    """
    try:
        channel.send(kind, title, body)
    except Exception as error:
        # Any failure, such as a timeout or a missing osascript, must not reach the caller.
        structlog.get_logger().warning(
            "notify.failed", kind=kind, title=title, error_type=type(error).__name__
        )
        return False
    structlog.get_logger().info("notify.sent", kind=kind, title=title)
    return True


def notifier_for(channel: Channel) -> Notify:
    """The `notify(kind, title, body)` callers use, with the configured channel bound."""

    def send(kind: NotifyKind, title: str, body: str) -> bool:
        return notify(channel, kind, title, body)

    return send
