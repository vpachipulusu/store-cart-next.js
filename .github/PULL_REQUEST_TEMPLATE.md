## Jira

KAN-<n> — <title>

## Summary

What changed and why, in terms of the story's acceptance criteria. List each criterion and how it is met.

## Verification

Commands you ran and their results. CI runs lint, typecheck, unit tests and the backend checks, but **E2E is off in CI**, so E2E specs must be run locally.

- [ ] Frontend: `npm run lint`, `npm run typecheck`, `npm run test:unit`, prettier on changed files
- [ ] Backend: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest --cov`
- [ ] E2E / real-route tests run locally and passing: `<exact command>` → `<result>` (if something could not run, say exactly what blocked it)

## Review

- [ ] ECC reviewers run on this diff (security-reviewer for auth, payments, secrets, SQL and external calls; the language reviewer; database-reviewer for migrations). CRITICAL and HIGH findings fixed. Result: `<summary>`
- [ ] No secrets, connection strings or personal data in code, logs or error messages

## Notes for the reviewer

Migrations, new environment variables, deploy steps, files outside the story's area, or follow-ups. Coordinator-owned files (`.env.example`, `.claude/CLAUDE.md`, `known-issues.md`) are not edited in feature branches.
