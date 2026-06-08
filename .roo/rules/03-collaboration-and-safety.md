# Collaboration And Safety

Change discipline:

- Respect existing code conventions and project architecture.
- Do not revert unrelated local changes.
- Keep diffs minimal and purpose-driven.
- If a generated file is edited manually, move custom logic outside generated outputs.

Git discipline:

- Use non-destructive commands by default.
- Avoid destructive git operations unless explicitly requested.
- Keep commit messages short, max one line.

Security and secrets:

- Never hardcode secrets or tokens.
- Do not log sensitive data.
- Prefer environment variables and existing auth/config pipelines.

Communication style for agent outputs:

- Summarize what changed and why.
- Include risks, assumptions, and follow-up actions when relevant.
- Be concise but specific.
