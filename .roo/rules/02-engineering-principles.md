# Generic Software Engineering Rules for Roo Code

## Core principles
- Optimize for correctness first, speed second, cleverness never.
- Before writing new code, scan existing patterns and follow local conventions.
- Prefer small, reversible changes over broad rewrites.
- Surface assumptions explicitly. If unsure, leave a clear note in code comments.

## Quality bar
- No dead code, no commented-out legacy blocks, no TODO without context.
- Every behavior change should include tests (unit or integration).
- Keep functions focused: one responsibility, clear inputs, deterministic outputs.
- Name things by domain intent, not implementation details.
- Add brief comments only where intent is not obvious.

## Change discipline
- Keep diffs reviewable (<400 lines where possible).
- Separate refactor commits from feature commits.
- Include migration/rollback notes for schema or infra changes.