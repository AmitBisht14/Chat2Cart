import structlog

from chat2cart.swiggy.client import SwiggyClient
from chat2cart.swiggy.errors import SwiggyError

GO_TO_TOOL = "your_go_to_items"
ORDERS_TOOL = "get_orders"


async def load_hints(client: SwiggyClient, address_id: str) -> set[str]:
    """The variant ids (spinId) of the user's go-to items and recent orders.

    Used only to break ties between variants that already fit. get_orders only returns orders
    from the last 15 days, so no date filtering is done here. If either call fails the answer is
    an empty set and matching goes on without hints.
    """
    try:
        go_to = await client.call_tool(GO_TO_TOOL, {"addressId": address_id})
        orders = await client.call_tool(ORDERS_TOOL)
    except SwiggyError as error:
        structlog.get_logger().warning("hints_unavailable", error_type=type(error).__name__)
        return set()
    return spin_ids_in(go_to) | spin_ids_in(orders)


def spin_ids_in(payload: object) -> set[str]:
    """Every `spinId` string anywhere in a response, whatever the nesting of products or orders."""
    if isinstance(payload, dict):
        own = {
            value for key, value in payload.items() if key == "spinId" and isinstance(value, str)
        }
        return own.union(*(spin_ids_in(value) for value in payload.values()))
    if isinstance(payload, list):
        return set[str]().union(*(spin_ids_in(value) for value in payload))
    return set()
