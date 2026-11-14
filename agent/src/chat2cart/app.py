import signal
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import structlog
import typer
from apscheduler.schedulers.background import BackgroundScheduler

from chat2cart.cart.worker import FailureHook, start_cart_worker
from chat2cart.cli import HTTP_TIMEOUT_SECONDS, build_swiggy_client
from chat2cart.config import CONFIG_ERROR_EXIT_CODE, Settings, load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.inbox import start_inbox_consumer
from chat2cart.llm.adapter import LLMAdapter
from chat2cart.logging import configure_logging
from chat2cart.notify.channels import notify_from_settings
from chat2cart.ops.failures import (
    alert_for_error,
    check_health,
    schedule_health_check,
)
from chat2cart.pipeline.handler import pipeline_job_handler
from chat2cart.pipeline.state import PipelineDeps
from chat2cart.scheduling.queueing import MessageHandler, message_handler
from chat2cart.scheduling.release import (
    build_scheduler,
    release_queue,
    schedule_debounce_release,
)
from chat2cart.secrets import KeychainSecretStore
from chat2cart.swiggy.errors import BadInputError
from chat2cart.understanding.rulebook import RuleBookError, load_rulebook

HEALTH_POLL_SECONDS = 5.0
PART_DIED_EXIT_CODE = 1


class Part(Protocol):
    def is_alive(self) -> bool: ...

    def stop(self) -> None: ...


class SchedulerPart:
    """The release scheduler, started and stopped like the background loops."""

    def __init__(self, scheduler: BackgroundScheduler) -> None:
        self._scheduler = scheduler
        scheduler.start()

    def is_alive(self) -> bool:
        return bool(self._scheduler.running)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)


class Service:
    """The running background parts of the agent."""

    def __init__(self, parts: list[Part]) -> None:
        self._parts = parts

    def is_alive(self) -> bool:
        return all(part.is_alive() for part in self._parts)

    def stop(self) -> None:
        for part in self._parts:
            part.stop()


def main() -> Service:
    """Start-up: migrate the database, check the rule book, start the inbox and the cart worker."""
    settings = load_settings()
    configure_logging(settings)
    _load_rulebook_or_exit(settings.rulebook_path)
    with closing(connect(settings.db_path)) as conn:
        version = migrate(conn)
    structlog.get_logger().info("database_ready", schema_version=version)
    # A release missed while the app was down or the Mac asleep happens now, if inside the window.
    _release_queue(settings)
    handler = pipeline_job_handler(settings.db_path, lambda: _open_deps(settings))
    scheduler = build_scheduler(settings, lambda: _release_queue(settings))
    schedule_health_check(scheduler, lambda: _check_health(settings))
    service = Service(
        [
            start_cart_worker(settings.db_path, handler, on_failure=_alert_on_failure(settings)),
            start_inbox_consumer(settings.db_path, _message_handler(settings, scheduler)),
            SchedulerPart(scheduler),
        ]
    )
    structlog.get_logger().info("agent_started")
    return service


def run_until_stopped(
    service: Service, stop: threading.Event, poll_seconds: float = HEALTH_POLL_SECONDS
) -> int:
    """Block until stop is set or a part dies; the exit code tells the supervisor to restart."""
    while not stop.wait(timeout=poll_seconds):
        if not service.is_alive():
            structlog.get_logger().error("agent_part_died")
            service.stop()
            return PART_DIED_EXIT_CODE
    service.stop()
    return 0


def serve() -> int:
    """Run the agent as a process: stop cleanly on SIGINT/SIGTERM, exit non-zero if a part dies."""
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    return run_until_stopped(main(), stop)


def _now() -> datetime:
    return datetime.now(UTC)


def _release_queue(settings: Settings) -> None:
    with closing(connect(settings.db_path)) as conn:
        release_queue(conn, _now(), settings)


def _check_health(settings: Settings) -> None:
    with closing(connect(settings.db_path)) as conn:
        check_health(conn, _now(), notify_from_settings(settings))


def _alert_on_failure(settings: Settings) -> FailureHook:
    def alert(conn: sqlite3.Connection, error: Exception) -> None:
        alert_for_error(conn, error, notify_from_settings(settings), _now())

    return alert


def _message_handler(settings: Settings, scheduler: BackgroundScheduler) -> MessageHandler:
    def schedule_release(run_at: datetime) -> None:
        schedule_debounce_release(scheduler, run_at, lambda: _release_queue(settings))

    return message_handler(
        settings,
        lambda: _language_model(settings),
        debounce_minutes=settings.daytime_debounce_minutes,
        schedule_release=schedule_release,
    )


def _language_model(settings: Settings) -> LLMAdapter:
    return LLMAdapter.from_settings(settings, KeychainSecretStore())


@contextmanager
def _open_deps(settings: Settings) -> Iterator[PipelineDeps]:
    address_id = settings.default_address_id
    if address_id is None:
        raise BadInputError("No delivery address is chosen. Run chat2cart swiggy address.")
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http:
        yield PipelineDeps(
            llm=_language_model(settings),
            swiggy=build_swiggy_client(http),
            load_rulebook=lambda: load_rulebook(settings.rulebook_path),
            address_id=address_id,
            notify=notify_from_settings(settings),
        )


def _load_rulebook_or_exit(path: Path) -> None:
    """Fail fast on a missing or invalid rule book, naming each problem."""
    try:
        entries = load_rulebook(path)
    except RuleBookError as error:
        for line in error.errors:
            typer.echo(line, err=True)
        raise SystemExit(CONFIG_ERROR_EXIT_CODE) from None
    structlog.get_logger().info(
        "rulebook_loaded", entries=len({entry.name for entry in entries.values()})
    )


if __name__ == "__main__":
    raise SystemExit(serve())
