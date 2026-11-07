import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import httpx
import structlog
import typer

from chat2cart.background import BackgroundLoop
from chat2cart.cart.worker import enqueue_job, start_cart_worker
from chat2cart.cli import HTTP_TIMEOUT_SECONDS, build_swiggy_client
from chat2cart.config import CONFIG_ERROR_EXIT_CODE, Settings, load_settings
from chat2cart.db.connection import connect
from chat2cart.db.migrate import migrate
from chat2cart.inbox import InboxMessage, start_inbox_consumer
from chat2cart.llm.adapter import LLMAdapter
from chat2cart.logging import configure_logging
from chat2cart.pipeline.handler import pipeline_job_handler
from chat2cart.pipeline.state import PipelineDeps
from chat2cart.secrets import KeychainSecretStore
from chat2cart.swiggy.errors import BadInputError
from chat2cart.understanding.rulebook import RuleBookError, load_rulebook


class Service:
    """The running background parts of the agent."""

    def __init__(self, parts: list[BackgroundLoop]) -> None:
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
    handler = pipeline_job_handler(settings.db_path, lambda: _open_deps(settings))
    service = Service(
        [
            start_cart_worker(settings.db_path, handler),
            start_inbox_consumer(settings.db_path, enqueue_message_job),
        ]
    )
    structlog.get_logger().info("agent_started")
    return service


def enqueue_message_job(conn: sqlite3.Connection, message: InboxMessage) -> None:
    """Each accepted message becomes one cart job; the cart worker runs the pipeline."""
    enqueue_job(conn, "message", {"inbound_ids": [message.id], "text": message.text})


@contextmanager
def _open_deps(settings: Settings) -> Iterator[PipelineDeps]:
    address_id = settings.default_address_id
    if address_id is None:
        raise BadInputError("No delivery address is chosen. Run chat2cart swiggy address.")
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http:
        yield PipelineDeps(
            llm=LLMAdapter.from_settings(settings, KeychainSecretStore()),
            swiggy=build_swiggy_client(http),
            load_rulebook=lambda: load_rulebook(settings.rulebook_path),
            address_id=address_id,
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
