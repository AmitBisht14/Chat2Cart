# Architecture

Chat2Cart has two parts that share only a SQLite database (WAL mode). `listener/` (TypeScript, Node.js 20+) keeps the WhatsApp connection, filters messages to the allowed sender and writes accepted messages to the inbox table. `agent/` (Python 3.12+) reads the inbox, understands each message with an LLM and a rule book, and builds the Swiggy Instamart cart through the MCP server. The agent never places an order or starts a payment; it stops at the cart.

## Batch dedupe rule

Within one batch, duplicates are merged, never summed, so repeated reminders cannot inflate an order. Items are merged twice: by normalised name (lowercase, trimmed, spaces collapsed) before product matching, and by variant id after matching, so two names that resolve to the same product ("ande" and "eggs") become one line. When a group has one stated quantity, that quantity is used. When several are stated in the same unit, the larger wins. When the units differ, the first is kept. With no quantities, the item counts once. Each merged item keeps the ids of every inbound message it came from. Merging with items already in the Swiggy cart is a separate step (cart merge).
