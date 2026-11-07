from chat2cart.notify.base import NotifyKind


class RecordingNotify:
    """A notify function that records what it was asked to send and never sends anything."""

    def __init__(self, result: bool = True) -> None:
        self.sent: list[tuple[NotifyKind, str, str]] = []
        self._result = result

    def __call__(self, kind: NotifyKind, title: str, body: str) -> bool:
        self.sent.append((kind, title, body))
        return self._result
