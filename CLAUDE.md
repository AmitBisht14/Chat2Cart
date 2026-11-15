# Chat2Cart

- Plan: `docs/plan.md`. Paths, names and conventions: `docs/blueprint.md`.
- Coding standards: `.claude/rules/` (`core.md` always; `typescript.md` for `listener/`, `python.md` for `agent/`).
  Follow them for every code change. If they are not already in context, read them before writing code.
- Story workflow: `.claude/rules/story.md` applies to every GitHub issue. Read the story, then follow its
  implementation plan and acceptance criteria strictly, before any code change.
- Swiggy: every Swiggy call goes through `SwiggyClient` (`agent/src/chat2cart/swiggy/client.py`).
  Swiggy tools are never bound to the LLM; code decides which tool to call.
- Agent graph: `docs/agent-graph.md` is the flowchart of the agentic structure (pipeline nodes, routing, state,
  what each node calls, and the path from a WhatsApp message to the graph). Any change to it must update that page
  in the same pull request: adding, removing, renaming or reordering a node, changing a routing function or edge,
  changing the state a node reads or writes, changing which LLM or Swiggy call a node makes, or changing how jobs
  reach the pipeline (inbox, request queue, release, cart worker). Code in `agent/src/chat2cart/pipeline/` is the
  source of truth; if the page and the code disagree, fix the page.
- Protected file: `agent/src/chat2cart/swiggy/allowlist.py` (the only Swiggy tools the code may call).
  Changes need human review; the story runner (P02) does not auto-merge them. The required check `allowlist-review`
  stays red on a pull request that changes it until the owner adds the label `allowlist-approved`. Never add that label.
- Baileys: `@whiskeysockets/baileys` is pinned exactly to `7.0.0-rc14`. Chosen over stable 6.7.x because its message keys carry the
  LID alt fields the sender filter needs (P20), and it has no git-URL dependency (6.7.x pulls `libsignal` from GitHub, which the Docker image cannot install).
- Strict rule: never place an order. Checkout, payment and order-confirmation tools must never be called.
- Protected `main` (ruleset `protect-main`, `docs/repository-settings.md`): never push to `main`. Every change
  goes through a squash-merged pull request after the required checks `check`, `docker` and `allowlist-review` pass.
- Git: author and commit as `Amit Bisht <bishtamith@gmail.com>` (set `git config user.name/user.email` first).
  No Claude author, `Co-Authored-By` or session trailers in commit messages or PR descriptions.

## Layout and commands
- `listener/`: TypeScript (Node.js 20+), WhatsApp side only (Baileys). `agent/`: Python 3.12+ (uv), everything else.
  They share only the SQLite database. Full layout: `docs/blueprint.md`.
- `make install` installs both parts; `make lint`, `make typecheck`, `make test` run both; `make check` runs all three.
- Listener: `npm ci`, `npm run build|lint|typecheck|test`. Agent: `uv sync`, `uv run pytest|ruff check|mypy`.
- Docker, no local installs: `docker compose run --rm check` (install + `make check`), `docker compose run --rm shell`.
  The image holds only the toolchain; the repo is bind-mounted. `chat2cart login swiggy` and the Keychain do not work inside it.
  `osascript` is not there either: set `CHAT2CART_NOTIFY_CHANNEL=log` when the agent runs inside it.
- Tests never touch the network, the Keychain, WhatsApp or Swiggy.
