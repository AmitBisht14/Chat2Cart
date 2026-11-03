# Architecture

Chat2Cart has two parts that share only a SQLite database (WAL mode). `listener/` (TypeScript, Node.js 20+) keeps the WhatsApp connection, filters messages to the allowed sender and writes accepted messages to the inbox table. `agent/` (Python 3.12+) reads the inbox, understands each message with an LLM and a rule book, and builds the Swiggy Instamart cart through the MCP server. The agent never places an order or starts a payment; it stops at the cart.
