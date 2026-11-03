# Core coding standards (all code)

Read before writing any code. Language rules: `typescript.md` (listener/), `python.md` (agent/).

## Readable flow
- A file reads top-down like a story: imports, constants, types, public entry point, then helpers in the order they are called.
- The entry function is a short list of named steps; each step is a well-named function at one level of abstraction.
- Functions do one thing, stay under ~30 lines, take at most 3–4 parameters (else pass a typed object).
- Prefer early returns and guard clauses over nested `if`/`else`. Max nesting depth: 2.
- Pure logic separated from I/O (DB, network, Keychain, WhatsApp). I/O lives at the edges.
- One module = one responsibility. Split a file past ~250 lines.

## Comments
- Code explains *what* via names; comments only explain *why* (non-obvious decisions, external quirks, links to issues).
- No commented-out code, no restating comments, no banner comments.
- Docstrings only on public functions whose contract is not obvious from name and types.

## Naming
- Names say intent: `releaseQueuedRequests`, not `process`. Booleans read as questions: `isOpen`, `has_token`.
- No abbreviations except well-known ones (`id`, `url`, `db`, `llm`). Same concept = same name everywhere.

## No duplication (DRY)
- Search the codebase before writing a helper; reuse or extend what exists.
- Shared logic goes in the module the blueprint (`docs/blueprint.md`) assigns to that area, never copy-pasted.
- Constants, config keys, table names and tool names defined once and imported.
- Duplicate only when two uses are coincidentally similar and likely to diverge; never three times.

## SOLID
- **S**ingle responsibility: one reason to change per module, class or function.
- **O**pen/closed: add behaviour through new implementations (e.g. a new `Notifier`), not by editing `switch`/`if` chains.
- **L**iskov: implementations and fakes honour the full interface contract, including errors.
- **I**nterface segregation: small protocols/interfaces with only what callers use.
- **D**ependency inversion: depend on interfaces; inject dependencies (DB, clients, clock, secret store) through constructors or parameters. No hidden globals.

## Errors and safety
- Fail fast on invalid input at boundaries; validate external data with schemas (zod / pydantic).
- Raise or throw typed, domain-specific errors; never swallow exceptions or catch-all without re-raising or logging.
- Never log secrets or message bodies beyond what the redacting logger allows.
- Never call checkout, payment or order-confirmation tools. Only the allowlist in `agent/src/chat2cart/swiggy/allowlist.py` is permitted.

## Testing
- Every behaviour change ships with tests; tests mirror the source tree.
- Tests never touch the network, real Keychain, WhatsApp or Swiggy. Use the shared fakes and fixtures.
- Test name states the behaviour: `rejects_message_from_unknown_sender`.
- Arrange / Act / Assert, one behaviour per test, no logic in tests.

## Scope
- Change only what the task needs. Follow-ups become new issues.
- Follow paths and names in `docs/blueprint.md`; do not invent new folders.
- `make check` must pass before work is done.
