# Chat2Cart

- Plan: `docs/plan.md`. Paths, names and conventions: `docs/blueprint.md`.
- Coding standards: `.claude/rules/` (`core.md` always; `typescript.md` for `listener/`, `python.md` for `agent/`).
  Follow them for every code change. If they are not already in context, read them before writing code.
- Story workflow: `.claude/rules/story.md` applies to every GitHub issue. Read the story, then follow its
  implementation plan and acceptance criteria strictly, before any code change.
- Strict rule: never place an order. Checkout, payment and order-confirmation tools must never be called.
- Git: author and commit as `Amit Bisht <bishtamith@gmail.com>` (set `git config user.name/user.email` first).
  No Claude author, `Co-Authored-By` or session trailers in commit messages or PR descriptions.

## Layout and commands
- `listener/`: TypeScript (Node.js 20+), WhatsApp side only (Baileys). `agent/`: Python 3.12+ (uv), everything else.
  They share only the SQLite database. Full layout: `docs/blueprint.md`.
- `make install` installs both parts; `make lint`, `make typecheck`, `make test` run both; `make check` runs all three.
- Listener: `npm ci`, `npm run build|lint|typecheck|test`. Agent: `uv sync`, `uv run pytest|ruff check|mypy`.
- Tests never touch the network, the Keychain, WhatsApp or Swiggy.
