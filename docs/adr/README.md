# Architecture decision records

One record per decision group. The decision IDs (D1–D23) come from the decision table in
[`.claude/plans/storecart-plan.md`](../../.claude/plans/storecart-plan.md); the plan stays the summary, these
records hold the reasoning.

Jira: [KAN-29](https://storecart.atlassian.net/browse/KAN-29). These records must be accepted before KAN-30
(template adaptation) starts.

## Index

| ADR | Title | Plan decisions | Status |
|---|---|---|---|
| [001](0001-adopt-nextjs-fastapi-template.md) | Adopt the nextjs-fastapi-template backend | D20, D23 | Proposed |
| [002](0002-hosting-on-vercel.md) | Hosting: two Vercel projects and serverless services | D10, D13, D18, D19 | Proposed |
| [003](0003-nextjs-to-fastapi-authentication.md) | Authentication from the Next.js server to FastAPI | D14, D21 | Proposed |
| [004](0004-backend-layering.md) | Backend layering | D15 (data-access layer) | Proposed |
| [005](0005-per-store-database-access.md) | Per-store database access | D1, D15 | Proposed (D1 provisional until KAN-115) |
| [006](0006-docker-role.md) | Docker for local development and CI only | D20 (Docker Compose) | Proposed |
| [007](0007-rate-limit-keys.md) | Rate limits keyed by user, organisation or store | — (new) | Proposed |
| [008](0008-api-client-generation.md) | Typed API client generated from OpenAPI | D16, D17 | Proposed |
| [009](0009-email-with-resend.md) | Email through Resend from the backend | D22 | Proposed |
| [010](0010-accounts-and-payments-model.md) | Account structure, seller of record and platform revenue | D3, D4, D9 | Proposed |

### Coverage of the plan's decision table

Every decision in the plan's table maps to at least one ADR above. The plan numbers its decisions D1, D3, D4,
D9, D10 and D13–D23. **D2, D5–D8, D11 and D12 are not in the plan or its git history**, so no ADR records them.
If they were dropped on purpose, nothing more is needed. If they were lost, they need adding to the plan first.

## Statuses

- **Proposed:** written, awaiting product owner sign-off on KAN-29.
- **Accepted:** signed off; change only by a new ADR that supersedes it.
- **Provisional:** accepted as the working decision but due for review at a named checkpoint (ADR-005, after the
  KAN-115 latency spike).
- **Superseded by ADR-NNN:** replaced; kept for history.

## Template

```markdown
# ADR-NNN: Title

- **Status:** Proposed
- **Date:** YYYY-MM-DD
- **Plan decisions:** Dn
- **Jira:** KAN-n

## Context
## Decision
## Alternatives considered
## Consequences
```
