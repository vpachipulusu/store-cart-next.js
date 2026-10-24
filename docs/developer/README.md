# StoreCart developer documentation

**Last updated:** 2026-10-11
**Scope:** the repository as it is on `main`. Items marked _(lands with KAN-n)_ are on unmerged branches and are not yet in `main`.

If you are setting up a machine for the first time, start with [getting-started.md](getting-started.md).

| Page                                                 | Read it when                                                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------- |
| [getting-started.md](getting-started.md)             | Installing prerequisites, cloning, configuring env, running both apps     |
| [architecture.md](architecture.md)                   | You need the monorepo layout and the request flow from browser to FastAPI |
| [workflow.md](workflow.md)                           | You pick up a Jira story, branch, commit, or open a PR                    |
| [testing.md](testing.md)                             | You run or write unit, integration, e2e, foundation, or backend tests     |
| [local-e2e.md](local-e2e.md)                         | You run Playwright E2E locally (setup, one command, timings, quarantine)  |
| [vercel-previews.md](vercel-previews.md)             | Only `main` deploys on Vercel; how to opt in to a branch preview          |
| [security.md](security.md)                           | You write a server action, handle secrets, or touch e2e accounts          |
| [dashboard-store-scope.md](dashboard-store-scope.md) | You scope a dashboard page, action or API call to the selected store      |
| [admin-settings.md](admin-settings.md)               | You work on the admin settings page, currency, language or feature flags  |
| [known-issues.md](known-issues.md)                   | Something is broken and you want to know whether it is already tracked    |
| [template-export.md](template-export.md)             | You work on the boilerplate template export (KAN-145): file classification |

## Related sources

- Architecture decisions: [docs/adr/README.md](../adr/README.md) (ADR-001 to ADR-011). The ADRs are the reference; these pages link to them rather than repeat them.
- Plan of record: [.claude/plans/storecart-plan.md](../../.claude/plans/storecart-plan.md)
- Agent and workflow rules: [.claude/CLAUDE.md](../../.claude/CLAUDE.md)
