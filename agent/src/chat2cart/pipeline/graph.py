import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, cast

import structlog
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from chat2cart.pipeline import nodes
from chat2cart.pipeline.state import OrderState, PipelineDeps, PipelinePayload
from chat2cart.swiggy.errors import DomainError


class PipelineStopped(Exception):
    """Swiggy reported a business error mid-run. `state` is what the run had when it stopped."""

    def __init__(self, error: DomainError, state: OrderState) -> None:
        super().__init__(error.message)
        self.error = error
        self.state = state


Node = Callable[[OrderState, PipelineDeps], Awaitable[OrderState]]
NODES: dict[str, Node] = {
    "classify": nodes.classify,
    "extract": nodes.extract,
    "apply_rulebook": nodes.apply_rulebook,
    "resolve": nodes.resolve,
    "merge_cart": nodes.merge_cart,
    "report": nodes.report,
}


def build_graph(deps: PipelineDeps) -> CompiledStateGraph[OrderState, None, OrderState, OrderState]:
    """classify, extract, apply rule book, resolve, merge cart, report: the order of plan 2.1."""
    graph = StateGraph(OrderState)
    for name, node in NODES.items():
        # mypy cannot match langgraph's add_node overloads to a TypedDict state (it lacks the
        # ClassVar members their protocol names); the call is correct at runtime.
        graph.add_node(name, _logged(name, node, deps))  # type: ignore[call-overload]
    graph.set_conditional_entry_point(_start_at)
    graph.add_conditional_edges("classify", _after_classify)
    graph.add_edge("extract", "apply_rulebook")
    graph.add_edge("apply_rulebook", "resolve")
    graph.add_conditional_edges("resolve", _after_resolve)
    graph.add_edge("merge_cart", "report")
    graph.add_edge("report", END)
    return graph.compile()


async def run_pipeline(
    payload: dict[str, object], deps: PipelineDeps, dry_run: bool = False
) -> OrderState:
    """Run one job through the graph. Every log line of the run carries the same run_id."""
    job = PipelinePayload.model_validate(payload)
    run_id = uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(run_id=run_id)
    try:
        start: OrderState = {
            "run_id": run_id,
            "inbound_ids": job.inbound_ids,
            "text": job.text,
            "dry_run": dry_run,
            "skipped": [],
        }
        if job.extracted:
            start["extracted"] = job.extracted
        return await _run_graph(build_graph(deps), start)
    finally:
        structlog.contextvars.unbind_contextvars("run_id")


async def _run_graph(
    graph: CompiledStateGraph[OrderState, None, OrderState, OrderState], start: OrderState
) -> OrderState:
    """Run to the end. A Swiggy business error stops the run, with the state reached so far."""
    latest = start
    try:
        async for state in graph.astream(start, stream_mode="values"):
            latest = cast(OrderState, state)
    except DomainError as error:
        raise PipelineStopped(error, latest) from error
    return latest


def _start_at(state: OrderState) -> Literal["classify", "apply_rulebook"]:
    """Items already extracted (an overnight batch) skip classify and extract."""
    return "apply_rulebook" if state.get("extracted") else "classify"


def _after_classify(state: OrderState) -> Literal["extract", "report"]:
    """A general or unsure message goes straight to the report and never reaches Swiggy."""
    return "extract" if state["intent"].order_text is not None else "report"


def _after_resolve(state: OrderState) -> Literal["merge_cart", "report"]:
    return "merge_cart" if state["resolved"] else "report"


def _logged(
    name: str, node: Node, deps: PipelineDeps
) -> Callable[[OrderState], Awaitable[OrderState]]:
    """Wrap a node so its input and output are logged under the run's id."""

    async def run(state: OrderState) -> OrderState:
        update = await node(state, deps)
        structlog.get_logger().info(
            "pipeline_step", node=name, input=_describe(state), output=_describe(update)
        )
        return update

    return run


def _describe(state: OrderState) -> dict[str, object]:
    """Sizes and labels only: the log shows what each step saw and produced, never message text."""
    return {key: _size(value) for key, value in state.items() if key != "run_id"}


def _size(value: object) -> object:
    if isinstance(value, list | str):
        return len(value)
    if isinstance(value, bool):
        return value
    label = getattr(value, "label", None)
    return label if isinstance(label, str) else type(value).__name__
