import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import structlog

from chat2cart.cart.outcomes import (
    NOT_SERVICEABLE_REASON,
    AddressNotServiceableError,
    is_not_serviceable,
)
from chat2cart.cart.worker import JobHandler
from chat2cart.db.connection import connect
from chat2cart.db.repos import enqueue_request
from chat2cart.pipeline.graph import PipelineStopped, run_pipeline
from chat2cart.pipeline.state import OrderState, PipelineDeps
from chat2cart.swiggy.oauth import utc_now

INSERT_RUN = (
    "INSERT INTO runs (id, job_id, started_at, finished_at, result_json) VALUES (?, ?, ?, ?, ?)"
)

OpenDeps = Callable[[], AbstractContextManager[PipelineDeps]]


def pipeline_job_handler(
    db_path: Path, open_deps: OpenDeps, clock: Callable[[], datetime] = utc_now
) -> JobHandler:
    """A cart job handler that runs the order pipeline and records the run.

    open_deps gives a fresh set of dependencies for each job and closes them afterwards.
    """

    def handle(_source: str, payload: dict[str, object]) -> None:
        started = clock()
        try:
            with open_deps() as deps:
                state = asyncio.run(run_pipeline(payload, deps))
        except PipelineStopped as stopped:
            _fail_job(db_path, stopped, clock)
        else:
            _record_run(db_path, state, started, clock())

    return handle


def _fail_job(db_path: Path, stopped: PipelineStopped, clock: Callable[[], datetime]) -> NoReturn:
    """Fail the job on a Swiggy business error. Nothing is retried.

    When the address is not serviceable the requests go back in the queue first, so nothing is lost.
    """
    if not is_not_serviceable(stopped.error):
        raise stopped.error from None
    with closing(connect(db_path)) as conn:
        for inbound_id in stopped.state.get("inbound_ids", []):
            items = [i for i in stopped.state.get("extracted", []) if inbound_id in i.sources]
            enqueue_request(conn, inbound_id, items, clock)
    structlog.get_logger().warning("request_requeued", reason=NOT_SERVICEABLE_REASON)
    raise AddressNotServiceableError(NOT_SERVICEABLE_REASON) from stopped.error


def _record_run(db_path: Path, state: OrderState, started: datetime, finished: datetime) -> None:
    report = state["report"].model_dump(mode="json")
    with closing(connect(db_path)) as conn:
        conn.execute(
            INSERT_RUN,
            (state["run_id"], None, started.isoformat(), finished.isoformat(), json.dumps(report)),
        )
        conn.commit()
    structlog.get_logger().info("run_recorded", run_id=state["run_id"])
