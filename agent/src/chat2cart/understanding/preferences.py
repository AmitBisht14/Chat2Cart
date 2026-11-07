from decimal import Decimal

from chat2cart.understanding.rulebook import RuleEntry, normalise_name
from chat2cart.understanding.schemas import ExtractedItem, PreferencedItem, SkippedItem

DEFAULT_QUANTITY = 1
NO_RULE = "no_rule"


def apply_preferences(
    items: list[ExtractedItem], rulebook: dict[str, RuleEntry]
) -> tuple[list[PreferencedItem], list[SkippedItem]]:
    """Attach the rule book's brand, size and quantity to each item.

    An item is matched to a rule by its normalised name or alias. No fuzzy matching: an item with
    no rule is skipped as `no_rule`.
    """
    preferenced: list[PreferencedItem] = []
    skipped: list[SkippedItem] = []
    for item in items:
        rule = rulebook.get(normalise_name(item.name))
        if rule is None:
            skipped.append(SkippedItem(name=item.name, reason=NO_RULE))
        else:
            preferenced.append(_with_rule(item, rule))
    return preferenced, skipped


def _with_rule(item: ExtractedItem, rule: RuleEntry) -> PreferencedItem:
    has_message_quantity = item.quantity is not None
    return PreferencedItem(
        name=item.name,
        quantity=item.quantity if item.quantity is not None else _default_quantity(rule),
        # A unit from the message belongs to the message's quantity, not to a rule book default.
        unit=item.unit if has_message_quantity else None,
        brands=list(rule.brands),
        size=rule.size,
        substitute=rule.substitute,
    )


def _default_quantity(rule: RuleEntry) -> Decimal:
    default = rule.default_quantity or DEFAULT_QUANTITY
    return Decimal(max(default, rule.min_quantity or 0))
