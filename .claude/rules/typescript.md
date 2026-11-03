---
paths:
  - "listener/**"
  - "**/*.ts"
---

# TypeScript standards (listener/)

Applies on top of `core.md`. Node.js 20+, ESM, strict mode.

## Compiler and tooling
- `tsconfig`: `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `module`/`moduleResolution` `NodeNext`.
- ESLint (typescript-eslint, type-checked) + Prettier. Tests with Vitest. Zero warnings.
- ESM imports with explicit `.js` extensions; `import type` for type-only imports.

## Types
- No `any`. Use `unknown` and narrow. No non-null `!` assertions; handle the `undefined` case.
- Validate every external input (env, DB rows, Baileys payloads) with zod; derive types via `z.infer`.
- `type` for unions and data shapes, `interface` for injectable contracts.
- Prefer `readonly` fields and `as const` literals; model states as string-literal unions, not enums.
- Explicit return types on exported functions.

## Structure
- Named exports only; no default exports. No barrel `index.ts` re-export files.
- Small functions and plain objects over classes; use a class only when it holds state with a lifecycle (e.g. the socket connection).
- Inject dependencies (`db`, `logger`, `clock`) as parameters or a deps object; no module-level singletons except the logger.
- `async`/`await` only; no `.then()` chains. Never leave a promise floating.

## Errors and logging
- Throw `Error` subclasses with a clear message and `cause`. Catch only where you can handle or add context.
- Log with the shared pino logger (`src/logger.ts`), structured fields, no string concatenation, no `console.log`.

## Example shape
```ts
export async function handleIncoming(msg: WAMessage, deps: IntakeDeps): Promise<void> {
  if (!isAcceptedSender(msg, deps.sender)) return;
  if (!passesIntakeRules(msg)) return;
  saveToInbox(deps.db, toInboxRow(msg));
}
```
