# Chat2Cart

- Plan: `docs/plan.md`. Paths, names and conventions: `docs/blueprint.md`.
- Coding standards: `.claude/rules/` (`core.md` always; `typescript.md` for `listener/`, `python.md` for `agent/`).
  Follow them for every code change. If they are not already in context, read them before writing code.
- Strict rule: never place an order. Checkout, payment and order-confirmation tools must never be called.
- Git: author and commit as `Amit Bisht <bishtamith@gmail.com>` (set `git config user.name/user.email` first).
  No Claude author, `Co-Authored-By` or session trailers in commit messages or PR descriptions.
