from collections.abc import Iterable

from chat2cart.cart.outcomes import MIN_ORDER_RUPEES
from chat2cart.pipeline.state import RunReport

NONE = "none"
UNKNOWN_REASON = "unknown"
REMINDER = (
    "Keep the Swiggy app closed until this summary arrives. Review and pay in the app yourself."
)


def compose_summary(report: RunReport) -> str:
    """The text of the summary sent after a cart update. Fixed lines, in a fixed order."""
    lines = [
        f"Added: {_added(report)}",
        f"Skipped: {_skipped(report)}",
        f"Reduced: {_reduced(report)}",
        f"Total: {_total(report)}",
    ]
    if report.diffs:
        lines.append(f"Mismatch: {_mismatch(report)}")
    if report.below_minimum:
        lines.append(f"Below the ₹{MIN_ORDER_RUPEES} minimum order.")
    lines.append(REMINDER)
    return "\n".join(lines)


def _added(report: RunReport) -> str:
    return _joined(f"{item.variant_name} x {item.quantity}" for item in report.added)


def _skipped(report: RunReport) -> str:
    return _joined(f"{item.name} ({item.reason or UNKNOWN_REASON})" for item in report.skipped)


def _reduced(report: RunReport) -> str:
    return _joined(f"{item.name} {item.requested}->{item.applied}" for item in report.reduced)


def _mismatch(report: RunReport) -> str:
    """Where the cart read back differs from what was written: wanted->found, by product name."""
    names = {item.spin_id: item.variant_name for item in report.added}
    return _joined(
        f"{names.get(diff.spin_id, diff.spin_id)} {_count(diff.intended)}->{_count(diff.actual)}"
        for diff in report.diffs
    )


def _count(quantity: int | None) -> str:
    return NONE if quantity is None else str(quantity)


def _total(report: RunReport) -> str:
    return UNKNOWN_REASON if report.total is None else f"₹{report.total}"


def _joined(parts: Iterable[str]) -> str:
    return ", ".join(parts) or NONE
