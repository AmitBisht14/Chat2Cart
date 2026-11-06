# Chat2Cart

- Plan: `docs/plan.md`. Paths, names and conventions: `docs/blueprint.md`.
- Coding standards: `.claude/rules/` (`core.md` always; `typescript.md` for `listener/`, `python.md` for `agent/`).
  Follow them for every code change. If they are not already in context, read them before writing code.
- Story workflow: `.claude/rules/story.md` applies to every GitHub issue. Read the story, then follow its
  implementation plan and acceptance criteria strictly, before any code change.
- Swiggy: every Swiggy call goes through `SwiggyClient` (`agent/src/chat2cart/swiggy/client.py`).
  Swiggy tools are never bound to the LLM; code decides which tool to call.
- Protected file: `agent/src/chat2cart/swiggy/allowlist.py` (the only Swiggy tools the code may call).
  Changes need human review; the story runner (P02) does not auto-merge them.
- Strict rule: never place an order. Checkout, payment and order-confirmation tools must never be called.
- Git: author and commit as `Amit Bisht <bishtamith@gmail.com>` (set `git config user.name/user.email` first).
  No Claude author, `Co-Authored-By` or session trailers in commit messages or PR descriptions.

## Layout and commands
- `listener/`: TypeScript (Node.js 20+), WhatsApp side only (Baileys). `agent/`: Python 3.12+ (uv), everything else.
  They share only the SQLite database. Full layout: `docs/blueprint.md`.
- `make install` installs both parts; `make lint`, `make typecheck`, `make test` run both; `make check` runs all three.
- Listener: `npm ci`, `npm run build|lint|typecheck|test`. Agent: `uv sync`, `uv run pytest|ruff check|mypy`.
- Docker, no local installs: `docker compose run --rm check` (install + `make check`), `docker compose run --rm shell`.
  The image holds only the toolchain; the repo is bind-mounted. `chat2cart login swiggy` and the Keychain do not work inside it.
- Tests never touch the network, the Keychain, WhatsApp or Swiggy.
