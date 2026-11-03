---
paths:
  - "agent/**"
  - "**/*.py"
---

# Python standards (agent/)

Applies on top of `core.md`. Python 3.12+, managed with uv.

## Tooling
- Ruff for lint and format (line length 100), mypy `--strict`, pytest. Zero warnings.
- Dependencies added only via `uv add`; no unpinned ad-hoc installs.

## Types
- Full type hints on every function, including return types. Modern syntax: `list[str]`, `X | None`.
- No bare `Any`; no `# type: ignore` without a reason.
- External data (LLM output, Swiggy responses, DB rows, config) parsed into pydantic models at the boundary.
- `typing.Protocol` for injectable contracts (`SecretStore`, `Notifier`); `@dataclass(frozen=True)` or pydantic for values.
- `Enum`/`Literal` for fixed state sets, matching the SQLite `CHECK` values.

## Structure
- Module-level functions by default; classes only for stateful collaborators or protocol implementations.
- Dependencies passed into constructors/functions; no module-level clients, connections or mutable globals.
- `pathlib.Path` for paths, `zoneinfo` for time (Asia/Kolkata), never naive datetimes.
- Inject a clock where time matters so tests stay deterministic.
- Context managers for connections and files.

## Errors and logging
- Raise from the domain hierarchy (`swiggy/errors.py` etc.); chain with `raise ... from err`.
- Never bare `except:` or `except Exception: pass`.
- Log with structlog (`chat2cart.logging`), key-value fields, no `print`, no f-strings in log events.

## Tests
- pytest functions, not classes; fixtures in `conftest.py`; fakes from `tests/fakes/`, data from `tests/fixtures/`.
- `pytest.mark.parametrize` instead of copy-pasted tests.

## Example shape
```python
def process_message(message: InboundMessage, deps: PipelineDeps) -> CartSummary:
    intent = classify(message.text, deps.llm)
    if intent is not Intent.ORDER:
        return CartSummary.ignored(message.id)
    items = extract_items(message.text, deps.llm)
    resolved = resolve_items(items, deps.swiggy)
    return write_and_verify_cart(resolved, deps.swiggy)
```
