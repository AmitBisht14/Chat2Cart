from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel, Field

from chat2cart.cart.merge import CartDiff, MergeResult
from chat2cart.llm.adapter import StructuredLLM
from chat2cart.swiggy.cart import CartItem, ReducedItem
from chat2cart.swiggy.client import SwiggyClient
from chat2cart.understanding.rulebook import RuleEntry
from chat2cart.understanding.schemas import (
    ExtractedItem,
    Intent,
    IntentLabel,
    PreferencedItem,
    ResolvedItem,
    SkippedItem,
)


@dataclass(frozen=True)
class PipelineDeps:
    """Everything the pipeline talks to. Swiggy is reached only through the guarded client."""

    llm: StructuredLLM
    swiggy: SwiggyClient
    load_rulebook: Callable[[], dict[str, RuleEntry]]
    address_id: str


class PipelinePayload(BaseModel):
    """A cart job's input. With `extracted` items it starts at the rule book, not at classify."""

    inbound_ids: list[str]
    text: str = ""
    extracted: list[ExtractedItem] = Field(default_factory=list)


class RunReport(BaseModel):
    """What a run did: the items added or skipped, what Swiggy changed, and the cart total."""

    intent: IntentLabel | None
    dry_run: bool
    added: list[ResolvedItem]
    skipped: list[SkippedItem]
    removed: list[CartItem]
    reduced: list[ReducedItem]
    diffs: list[CartDiff]
    total: Decimal | None
    sources: list[str]


class OrderState(TypedDict, total=False):
    run_id: str
    inbound_ids: list[str]
    text: str
    order_text: str
    dry_run: bool
    intent: Intent
    extracted: list[ExtractedItem]
    preferenced: list[PreferencedItem]
    resolved: list[ResolvedItem]
    skipped: list[SkippedItem]
    merge_result: MergeResult
    report: RunReport
