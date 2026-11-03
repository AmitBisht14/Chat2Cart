# Chat2Cart implementation blueprint (shared by every story plan)

Every story's implementation plan MUST use the paths, names and conventions below. Do not invent alternative
folders or module names. If a story genuinely needs a new module, put it in the folder this blueprint assigns
to that area and name it in the plan.

Repository: AmitBisht14/Chat2Cart (default branch `main`).

## Language split
- `listener/`: TypeScript, Node.js 20+, ESM. Only the WhatsApp side: Baileys connection, `chat2cart-wa` CLI
  (login, logout), sender filter, intake rules, writing accepted messages and connection state to SQLite.
- `agent/`: Python 3.12+, managed with uv. Everything else: config, Keychain secrets, Swiggy OAuth and MCP
  client, allowlist, LLM, rule book, LangGraph pipeline, cart logic, scheduling, notifications, `chat2cart` CLI.
- They communicate ONLY through the shared SQLite database (WAL mode). No HTTP between them.

## Repository layout
```
/
  CLAUDE.md                     project rules for Claude (layout, commands, strict no-order rule, protected files)
  Makefile                      targets: install, lint, typecheck, test, check (= lint+typecheck+test, both parts)
  .env.example                  placeholders only
  .gitignore
  .github/workflows/ci.yml      runs `make check` on pull_request and push to main
  ecosystem.config.cjs          pm2: apps "chat2cart-listener" and "chat2cart-agent"
  rulebook.example.md           example rule book
  scripts/story-runner.sh       story loop (P02)
  scripts/story-runner/instructions.md   fixed instructions given to `claude -p` for every story
  docs/validation/              milestone-0.md, cart-behaviour.md, release-checklist.md
  docs/architecture.md          short architecture notes (kept up to date by stories that change it)
  listener/
    package.json  tsconfig.json  eslint.config.js  vitest.config.ts
    src/
      index.ts                  start the listener service
      cli.ts                    `chat2cart-wa` entry (commands: login, logout)
      config.ts                 zod schema over the shared .env (listener subset)
      logger.ts                 pino with redaction
      db.ts                     better-sqlite3 connection, WAL, schema version check
      whatsapp/connection.ts    Baileys socket, auth state, reconnect
      whatsapp/login.ts         QR and pairing-code login flows
      whatsapp/state.ts         writes whatsapp_state (state + heartbeat)
      intake/senderFilter.ts    phone/@lid matching
      intake/lidMap.ts          lid_map table read/write
      intake/rules.ts           direct-chat/text-only/fromMe rules
      intake/inbox.ts           INSERT OR IGNORE into inbound_messages
    test/                       vitest tests, mirrors src/
  agent/
    pyproject.toml              package `chat2cart`, console script `chat2cart = chat2cart.cli:app` (Typer)
    src/chat2cart/
      cli.py                    Typer app; sub-apps: login, secrets, swiggy, logout, status, prototype
      app.py                    long-running service: migrations, inbox consumer, scheduler, cart worker
      config.py                 pydantic-settings Settings
      secrets.py                SecretStore protocol, KeychainSecretStore (keyring), InMemorySecretStore
      logging.py                structlog JSON lines, redaction processor, run_id contextvar
      db/connection.py          sqlite3 connection factory (WAL, foreign keys)
      db/migrate.py             applies db/migrations/NNN_*.sql in order, records schema_meta.version
      db/migrations/001_init.sql
      db/repos.py               small repository functions per table
      swiggy/oauth.py           DCR, PKCE S256, localhost callback server, code exchange
      swiggy/tokens.py          TokenSet model, TokenManager (refresh, rotation, needs_login)
      swiggy/errors.py          SwiggyError hierarchy (AuthError, BadInputError, UpstreamError, DomainError, BlockedToolError, NeedsLoginError)
      swiggy/allowlist.py       ALLOWED_TOOLS (PROTECTED FILE)
      swiggy/client.py          SwiggyClient: MCP Python SDK streamable HTTP, auth, allowlist check, retries
      swiggy/addresses.py       list/choose addresses
      swiggy/products.py        Product/Variant models, search()
      swiggy/cart.py            Cart models, read_cart(), write_cart() (full replacement)
      swiggy/history.py         go-to items, recent orders
      llm/adapter.py            LLMAdapter over a LangChain chat model, structured output
      llm/prompts.py            prompt templates
      understanding/schemas.py  pydantic: Intent, ExtractedItem, ResolvedItem, SkippedItem
      understanding/classify.py
      understanding/extract.py
      understanding/rulebook.py parser + validation + reload
      understanding/preferences.py   apply rule book
      understanding/resolve.py  variant choice + unit conversion
      understanding/hints.py    go-to/order-history tie breaking
      understanding/dedupe.py   normalise + merge
      cart/merge.py             read-merge-write-verify
      cart/worker.py            single serial worker over cart_jobs
      cart/outcomes.py          min order, serviceability, stock outcome handling
      pipeline/state.py         OrderState TypedDict/pydantic
      pipeline/graph.py         LangGraph StateGraph build_graph()
      pipeline/nodes.py         node functions
      scheduling/window.py
      scheduling/queue.py
      scheduling/release.py     APScheduler job at 07:00 Asia/Kolkata + catch-up
      scheduling/batching.py    overnight merge + daytime debounce
      notify/base.py            Notifier protocol, Notification model
      notify/macos.py           osascript notifier
      notify/summary.py         CartSummary composer
      ops/failures.py           failure policy + alert de-duplication
      ops/status.py             status report
    tests/                      pytest; tests/fakes/ (FakeSwiggyTransport, FakeLLM, InMemorySecretStore), tests/fixtures/ (recorded JSON)
```

## Shared SQLite schema (owned by agent/src/chat2cart/db/migrations/001_init.sql, evolved by later NNN files)
- schema_meta(version INTEGER)
- inbound_messages(id TEXT PRIMARY KEY  -- WhatsApp message id, chat_jid, sender_jid, sender_pn, text, received_at,
  status TEXT CHECK in pending|processing|done|failed, claimed_at, finished_at, error, run_id)
- whatsapp_state(id INTEGER PRIMARY KEY CHECK(id=1), state TEXT connected|reconnecting|logged_out|stopped,
  changed_at, heartbeat_at, detail)
- lid_map(lid TEXT PRIMARY KEY, pn TEXT, learned_at)
- request_queue(id INTEGER PK, inbound_id TEXT, items_json, queued_at, released_at, status queued|released|done)
- cart_jobs(id INTEGER PK, source TEXT, payload_json, status pending|running|done|failed, created_at, started_at, finished_at, error)
- runs(id TEXT PK, job_id, started_at, finished_at, result_json)
- alerts(key TEXT PK, last_sent_at)
Stories may add columns or tables only through a new numbered migration file, and must say so in the plan.

## Key technical choices
- Swiggy: official MCP Python SDK (`mcp`), streamable HTTP to https://mcp.swiggy.com/im, bearer token header.
  Swiggy tools are NEVER bound to the LLM as tools. Code decides which tool to call; LLM output is data only.
- OAuth: OAuth 2.1 + PKCE S256, Dynamic Client Registration at POST https://mcp.swiggy.com/auth/register,
  authorize at /auth/authorize, token at /auth/token, logout at /auth/logout, redirect http://localhost/callback
  (exact match). Access token 5 days, refresh returns new refresh token (rotate), session 30 days idle.
- Secrets: `keyring` (macOS Keychain). Service name "chat2cart". Keys: swiggy.tokens (JSON), swiggy.client (JSON from DCR), llm.api_key.
- LLM: LangChain chat model chosen by config (provider + model), `with_structured_output(pydantic model)`.
- Pipeline: LangGraph StateGraph, plain functions per node, typed state.
- Scheduling: APScheduler in agent/app.py, all times Asia/Kolkata via zoneinfo.
- WhatsApp: Baileys pinned to an exact version (record choice in CLAUDE.md), auth via useMultiFileAuthState in the session folder.
- Errors/retries: exponential backoff with jitter 0.5s doubling to 8s, max 5 attempts, honour 429 Retry-After; domain failures never retried.
- Allowed Swiggy tools: get_addresses, search_products, your_go_to_items, get_cart, update_cart, get_orders, get_order_details. Everything else blocked.

## Engineering conventions (every plan should rely on these, not repeat them at length)
- Tests first where practical; no test touches the network, the real Keychain, a real WhatsApp account or real Swiggy.
- Use fakes in agent/tests/fakes and listener/test/fakes; recorded JSON fixtures for Swiggy responses.
- `make check` must pass before the story is done.
- Never log secrets; use the logging redaction.
- Never edit agent/src/chat2cart/swiggy/allowlist.py except in P09; any later change needs human review.
- Keep each story's change scoped to its plan; note follow-ups as new issues instead of expanding scope.
- Commit messages: Conventional Commits, e.g. `feat(agent): ...`, ending with the story reference `Refs #N`.

## Plan format (Markdown, used inside the issue body under the existing "## Implementation plan" heading)
Write the plan body WITHOUT the "## Implementation plan" heading itself (it already exists). Use exactly these
sub-headings, in this order:

**Approach**: 2 to 4 sentences on how the story will be implemented.

**Files**: bullet list of files to create or modify, each with a short purpose. Use blueprint paths.

**Steps**: numbered, concrete, ordered steps Claude follows. 5 to 12 steps. Name functions/classes/CLI commands.

**Tests**: bullet list of the tests to add (test file path + what each asserts).

**Out of scope**: 1 to 4 bullets of what NOT to do in this story (belongs to another story; reference P-number).

**Definition of done**: 2 to 4 bullets; always include "All acceptance criteria above are met" and "`make check` passes".
For stories labelled needs-manual-check, add a bullet saying which manual step the user performs and that the
runner must stop for the user after the code is merged.

Style: plain, specific, no filler, 250 to 550 words per plan. Use the exact tool names, table names and paths above.
