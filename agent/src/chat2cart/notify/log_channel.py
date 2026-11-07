from chat2cart.notify.base import NotifyKind


class LogChannel:
    """Sends nothing: notify() already writes a `notify.sent` log line. For use inside Docker."""

    def send(self, kind: NotifyKind, title: str, body: str) -> None:
        return None
