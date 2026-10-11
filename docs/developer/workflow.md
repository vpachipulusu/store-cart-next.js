# Development workflow

**Last updated:** 2026-10-11

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
2. Run the tests for the area you changed ([testing.md](testing.md)).
3. Open the PR against `main`. The summary covers all commits, and the test plan lists what you ran.
4. Comment the PR link on the Jira story and move the story to **In Review**.
5. Merge once review is done and CI is green. CI is not in the repo yet (lands with KAN-27).
6. Check the story's acceptance criteria against the merged code, then move the story to **Done**.

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
