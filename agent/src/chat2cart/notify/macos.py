import subprocess

from chat2cart.notify.base import NotifyKind

OSASCRIPT_TIMEOUT_SECONDS = 5


class MacosChannel:
    """Shows a macOS notification. It only works on a Mac: osascript is not in the Docker image."""

    def send(self, kind: NotifyKind, title: str, body: str) -> None:
        send_macos(f"Chat2Cart {kind}: {title}", body)


def send_macos(title: str, body: str) -> None:
    """Show a notification with a title and a body.

    The text goes in as arguments to the AppleScript, so it needs no escaping and no shell is used.
    """
    subprocess.run(
        [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
            title,
            body,
        ],
        timeout=OSASCRIPT_TIMEOUT_SECONDS,
        check=True,
    )
