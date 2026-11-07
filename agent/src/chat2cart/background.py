import threading
from collections.abc import Callable

JOIN_TIMEOUT_SECONDS = 10


class BackgroundLoop:
    """A daemon thread that runs body(stop_event) until stop() is called."""

    def __init__(self, name: str, body: Callable[[threading.Event], None]) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=body, args=(self._stop,), name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=JOIN_TIMEOUT_SECONDS)

    def is_alive(self) -> bool:
        return self._thread.is_alive()
