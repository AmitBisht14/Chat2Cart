from chat2cart.cart.merge import merge_into_cart
from chat2cart.cart.outcomes import capped_items, is_below_minimum, out_of_stock_skips
from chat2cart.pipeline.state import OrderState, PipelineDeps, RunReport
from chat2cart.understanding.classify import classify_message
from chat2cart.understanding.extract import extract_items
from chat2cart.understanding.preferences import apply_preferences
from chat2cart.understanding.resolve import resolve_items


async def classify(state: OrderState, deps: PipelineDeps) -> OrderState:
    intent = await classify_message(state["text"], deps.llm)
    return {"intent": intent, "order_text": intent.order_text or ""}


async def extract(state: OrderState, deps: PipelineDeps) -> OrderState:
    items = await extract_items(state["order_text"], deps.llm)
    sources = state["inbound_ids"]
    return {"extracted": [item.model_copy(update={"sources": sources}) for item in items]}


async def apply_rulebook(state: OrderState, deps: PipelineDeps) -> OrderState:
    preferenced, skipped = apply_preferences(state["extracted"], deps.load_rulebook())
    return {"preferenced": preferenced, "skipped": skipped}


async def resolve(state: OrderState, deps: PipelineDeps) -> OrderState:
    resolved, skipped = await resolve_items(state["preferenced"], deps.swiggy, deps.address_id)
    return {"resolved": resolved, "skipped": [*state["skipped"], *skipped]}


async def merge_cart(state: OrderState, deps: PipelineDeps) -> OrderState:
    result = await merge_into_cart(
        deps.swiggy, deps.address_id, state["resolved"], dry_run=state["dry_run"]
    )
    return {"merge_result": result}


async def report(state: OrderState, _deps: PipelineDeps) -> OrderState:
    merge_result = state.get("merge_result")
    intent = state.get("intent")
    removed = merge_result.removed if merge_result else []
    total = merge_result.bill_total if merge_result else None
    written = merge_result is not None and merge_result.actual is not None
    return {
        "report": RunReport(
            intent=intent.label if intent else None,
            dry_run=state["dry_run"],
            added=state.get("resolved", []),
            skipped=[*state.get("skipped", []), *out_of_stock_skips(removed)],
            removed=removed,
            reduced=capped_items(merge_result.reduced if merge_result else []),
            diffs=merge_result.diffs if merge_result else [],
            total=total,
            # The total of a dry run is the cart as it is now, so only a written cart is flagged.
            below_minimum=written and is_below_minimum(total),
            sources=state["inbound_ids"],
        )
    }
