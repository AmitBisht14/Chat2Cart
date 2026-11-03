# User story workflow (every story, before any code change)

Every GitHub issue is a user story and already contains its implementation plan. Implement it in this order, every time.

## 1. Understand the story first (no code yet)
- Read the issue title, user story, description, acceptance criteria, dependencies and notes in full.
- Read the `## Implementation plan` section: approach, files, steps, tests, out of scope, definition of done.
- Read `docs/blueprint.md` and the rules in `.claude/rules/` that apply.
- If the plan and the acceptance criteria conflict, or something is unclear, stop and ask the user. Do not guess.

## 2. Follow the implementation plan strictly
- Implement the plan's files, steps and tests as written, in the order given. Use the exact paths, names and commands it names.
- Do not add anything the plan does not ask for. Respect its "Out of scope" list; follow-ups become new issues.
- If the plan seems wrong or incomplete, raise it with the user instead of silently deviating.

## 3. Acceptance criteria are mandatory
- Every acceptance criterion must be met. Check them one by one before declaring the work done.
- Each criterion needs a test or a stated manual check that proves it.
- Do not close or merge a story with an unmet criterion; say which one is unmet and why.

## 4. Finish
- Meet the plan's "Definition of done", including `make check` passing.
- Stories labelled `needs-manual-check`: implement, open the pull request, then stop for the user to verify. Do not merge.
- Reference the story in commits (`Refs #N`) and close it from the pull request (`Closes #N`).
