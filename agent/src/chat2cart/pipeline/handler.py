import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from datetime import datetime
from pathlib import Path

import structlog

from chat2cart.cart.worker import JobHandler
from chat2cart.db.connection import connect
from chat2cart.pipeline.graph import run_pipeline
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
        with open_deps() as deps:
            state = asyncio.run(run_pipeline(payload, deps))
        _record_run(db_path, state, started, clock())

    return handle


def _record_run(db_path: Path, state: OrderState, started: datetime, finished: datetime) -> None:
    report = state["report"].model_dump(mode="json")
    with closing(connect(db_path)) as conn:
        conn.execute(
            INSERT_RUN,
            (state["run_id"], None, started.isoformat(), finished.isoformat(), json.dumps(report)),
        )
        conn.commit()
    structlog.get_logger().info("run_recorded", run_id=state["run_id"])
