# HANDOFF: baton between Claude and Codex

Rules for using this file are in [`AGENTS.md`](../../AGENTS.md). Read the table first. Update it in your own commit at every handoff.

| Field | Value |
|---|---|
| owner | **codex** (claude → codex; Claude hit its usage limit) |
| ticket | none in progress |
| branch | none (start from `main`) |
| main at handoff | efe371a (after PR #26, KAN-148) |
| open PRs | none besides the handover docs PR (`docs/handover-claude-codex`) |
| status | clean: nothing half-done |
| updated | 2026-10-13 by claude |

## Done so far

KAN-25, 27, 28, 29, 30, 113, 121, 122, 132 to 136, 138, 140, 146, 147, 148 (PR #26, merged 2026-10-13), 159.

Last change: `site.ts` is the single brand source (`NEXT_PUBLIC_APP_NAME`, optional `NEXT_PUBLIC_SUPPORT_EMAIL`), `app/manifest.ts` replaced
the two static manifests, unused packages removed. Capacitor untouched. `@capacitor/cli` stays at 6 (CLI 7 breaks `cap add android`); the tar audit
finding is recorded as accepted and dev-only in `docs/developer/known-issues.md`.

## Next steps for the next owner, in order

1. **Jira hygiene** (Jira only, no code): KAN-111 is In Review and merged; tick its acceptance criteria and move it to Done. KAN-3 ("Subtask 2.1") is a stale In Progress subtask: ask the owner before closing it. KAN-145 and KAN-112 were moved back to To-do on 2026-10-13.
2. **KAN-153** (false trial and 2FA text in app copy). Ordinary code, so PM pass. Pick it up per the Jira flow.
3. **Stop and ask the owner** before KAN-145. It has an explicit hold: the owner signals when to start.
4. **KAN-112** (backend on Vercel and Neon, with the follow-ups from the KAN-30 review) needs Vercel and Neon access: check the tools you have, and if you lack them, hand it back to Claude or the owner instead of guessing.
5. Later, in order: KAN-31 to KAN-51 (connect FastAPI to the frontend), KAN-149 (template v1.0), KAN-115 spike when the owner says it is ready.

## Context an agent cannot get from the code

- E2E: runs about 2 minutes locally using the dedicated `storecart-test` Firebase project and test database in `nextjs-frontend/.env.e2e.local` (local, not committed). The CI e2e job is enabled by the repo variable `E2E_ENABLED`, sits outside the gate, and is red only for known failures: KAN-154 (profile Email accessible name), 155 (website URL validation message), 156 (intermittent lost navigation), 157 (Stripe webhook routing for the upgrade test), 158 (admin dropdown test, yearly savings badge needs a discounted yearly test price).
- Branch protection on `main` is set. Vercel Preview vars point at test services.
- Owner's optional to-dos: delete the leftover `-yem8` GitHub environments; create a Stripe discounted yearly test price for KAN-158.
- KAN-145 ticket holds the classification and Capacitor decision (public repo `https://github.com/vpachipulusu/boiler-plate-fastapi-nextjs.git`, fresh single commit, secret scan, show the file list before pushing). Substitution points the export must handle beyond `site.ts`: `.env.example`, the CI env in `.github/workflows/e2e.yml` and `frontend.yml`, and the `layout.tsx` placeholders (`Your Name`, `@yourusername`).
- Developers use Sonnet and the PM reviewer uses Haiku when running under Claude; subagent reports stay under 150 words.
- Untracked files in the working tree (`.claude/worktrees/`, `kan113-runs.md`, `PRPs/`, `KAN-138-e2e.md`, `KAN-147.md`) are not part of any PR. Leave them.

## Log

| Date | From → to | Note |
|---|---|---|
| 2026-10-13 | claude → codex | Usage limit. KAN-148 merged; state clean. |
