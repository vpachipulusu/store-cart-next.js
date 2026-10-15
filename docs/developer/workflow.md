# Development workflow

**Last updated:** 2026-10-12

Work is tracked in the Jira project **Store Cart** (key `KAN`): https://storecart.atlassian.net/browse/KAN

## Statuses

Use the exact Jira status names: **To-do → In Progress → In Review → Done**.

## Picking up a story

1. Take only a story in **To-do**. JQL: `project = KAN AND issuetype = Story AND status = "To-do" ORDER BY key`.
2. Work epics in order (E1, then E2, and so on). Within Foundation, follow the **start order** in the plan, not key order, unless the product owner says otherwise. The Foundation start order is:

   KAN-25 → KAN-29 → KAN-112 and KAN-113 (in parallel) → KAN-111 → KAN-27 → KAN-30 → KAN-115 → KAN-31 and KAN-33 → KAN-32, KAN-34, KAN-35, KAN-26, KAN-28 → E3, E4, E5 (trimmed), E6.

3. Respect "Depends on" and "Blocks" notes in story descriptions.
4. Never take a story that is already In Progress or In Review.
5. Before writing any code, move the story to **In Progress** and comment that it was picked up and on which branch.

## Branches

Format: `<type>/KAN-<n>-<short-slug>`. Example: `fix/KAN-122-auth-action-takeover`.

Branch from `main` and keep one story per branch.

## Commits

Format: `<type>(KAN-<n>): <description>`, with an optional body. Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Example: `fix(KAN-122): remove unused auth API routes and the client plan argument`.

## Pull requests

1. Review the full branch before opening the PR: `git diff main...HEAD` and the commit list.
2. Run the tests for the area you changed ([testing.md](testing.md)). The pre-commit hooks (KAN-111) run ruff, mypy, ESLint, Prettier and `tsc` on staged files at commit time; install them as in [getting-started](getting-started.md#pre-commit-hooks).
3. Open the PR against `main`. The summary covers all commits, and the test plan lists what you ran.
4. Comment the PR link on the Jira story and move the story to **In Review**.
5. Merge once review is done and CI is green. CI is not in the repo yet (lands with KAN-27); until then, the author runs the checks in [testing.md](testing.md#before-you-open-a-pr) locally.
6. Check the story's acceptance criteria against the merged code, then move the story to **Done**.

## Local E2E is required for user-facing changes (KAN-165)

CI never runs Playwright (`E2E_ENABLED=false`, and it stays false), so the PR author is the only gate. **Before opening the PR, run the relevant Playwright specs locally** when the change touches any of:

- frontend pages, layouts, components or styles users see (`src/app/**`, `src/components/**`);
- auth or session handling (login, signup, session cookie, 2FA, re-authentication, `src/proxy.ts`);
- billing or subscriptions (pricing, checkout, org billing pages and actions);
- the proxy, security headers, rate limiting or the health endpoint.

**Exempt:** backend-only changes (they keep `pytest` and the real-route tests against a throwaway Postgres), docs-only and config-only changes (CI workflows, lint config). If you are unsure, run the specs.

How:

1. Run the focused specs for the area, for example `npm run test:e2e:local -- src/__tests__/e2e/dashboard.spec.ts`, from `nextjs-frontend/`. Setup, a backend and timings are in [local-e2e.md](local-e2e.md). Run the whole suite (no spec arguments) when the change is broad or touches auth, the proxy or shared layouts.
2. **Report it in the PR description**, in the "E2E / real-route tests" line of the PR template: the exact command, the passed/skipped/failed counts, and the base SHA. If a spec could not run, say exactly what blocked it. A skipped test did not run, so name skipped tests that belong to your area.
3. Reviewers (PM and Architect passes) check that line. A user-facing PR without it goes back to the author. Never edit an assertion to make a run green ([testing.md](testing.md#assertion-rule)).
4. A test that fails on a clean `main` is quarantined, never skipped silently: `test.fixme(...)` with the Jira key in a comment beside it, listed under [Quarantined tests](local-e2e.md#quarantined-tests), and tracked on that ticket. A test that fails because of your change is yours to fix.

## Definition of done

- The story's Jira **acceptance criteria are the definition of done**. Do not widen scope. Propose a new story for extra work.
- CI is green, and the change is reviewed and merged.

Foundation is done when every boilerplate feature works through FastAPI, the e2e suite passes, and the frontend has no `DATABASE_URL` or server secrets. The automated check for that is `npm run foundation:check` (lands with KAN-113; see [testing.md](testing.md)).

## Blocked work

Keep the story In Progress. Comment with the blocker and what is needed to unblock it. Do not abandon a story silently.

## Where documents go

- Plans and backlog: `.claude/plans/`.
- Architecture decisions: `docs/adr/`. Do not copy ADR content into other pages; link to it.
- Developer documentation: `docs/developer/`.
