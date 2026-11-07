# Architecture

Chat2Cart has two parts that share only a SQLite database (WAL mode). `listener/` (TypeScript, Node.js 20+) keeps the WhatsApp connection, filters messages to the allowed sender and writes accepted messages to the inbox table. `agent/` (Python 3.12+) reads the inbox, understands each message with an LLM and a rule book, and builds the Swiggy Instamart cart through the MCP server. The agent never places an order or starts a payment; it stops at the cart.

## Batch dedupe rule

Within one batch, duplicates are merged, never summed, so repeated reminders cannot inflate an order. Items are merged twice: by normalised name (lowercase, trimmed, spaces collapsed) before product matching, and by variant id after matching, so two names that resolve to the same product ("ande" and "eggs") become one line. When a group has one stated quantity, that quantity is used. When several are stated in the same unit, the larger wins. When the units differ, the first is kept. With no quantities, the item counts once. Each merged item keeps the ids of every inbound message it came from. Merging with items already in the Swiggy cart is a separate step (cart merge).

## Cart merge rule

`update_cart` replaces the whole cart, so every write is the full list: the lines already in the cart (hand-added ones included) plus the new items. When a variant is already in the cart, the larger quantity is kept, never the sum, so a job that is retried does not double it. After the write the cart is read back and any difference from the intended list is reported.

## Overnight batch

An overnight release produces one cart job, not one per request. Every queued request is released together, its items are tagged with the message they came from, and the pipeline then merges repeats by name and by variant (see "Batch dedupe rule"), so the morning has a single cart to review and each line still names its messages.

## Daytime batching delay

`CHAT2CART_DAYTIME_DEBOUNCE_MINUTES` (default 0) groups quick messages during the day. With 0, each message becomes a cart job at once. With a delay, an order message is understood and saved in the request queue, and one timer, set by the first message of the group, releases the queue when the delay ends; later messages join the open group without moving the timer, and the release makes one cart job for the group. A timer that fires after the window closes releases nothing, and the 07:00 release takes the group. If the app restarts while a group is waiting, the start-up release picks it up.
