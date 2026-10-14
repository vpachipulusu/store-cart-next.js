# HANDOFF: baton between Claude and Codex

Read `AGENTS.md` and [agent-handover.md](../../docs/developer/agent-handover.md) first.
This baton is the durable communication record; neither agent can read the other's chat.

| Field              | Value                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| owner              | **claude** (since PR #47)                                                                               |
| ticket             | none active; bug queue from the 2026-10-13 handover is complete; next ticket is an owner decision       |
| branch             | start from safely updated `main` in `C:\MainData\AI-Projects\store-cart-next.js`                        |
| last completed SHA | `e3c735fbb6024b41d2c2109235f57f4be842787c` (PR #57, KAN-129)                                            |
| handover revision  | resolve using Git history for this file; do not embed a self-referential SHA                            |
| open PRs           | none besides the PR that carries this baton refresh                                                     |
| status             | primary tracked tree clean; completed code/tests committed and published; unrelated scratch preserved   |
| blockers           | Jira not reachable from the 2026-10-14 Claude session (no Atlassian connector); statuses below unsynced |
| updated            | 2026-10-14 by claude (Europe/London)                                                                    |

A usage-limit reset does not transfer ownership. When the owner requests return to
Codex, finish a clean, published checkpoint, record exact ticket/branch/SHA/PR/checks/
blockers here and in Jira, transfer the baton to `codex`, and give the owner a startup prompt.

## Jira sync needed

The 2026-10-14 session could not reach Jira (Atlassian connector not connected), so the
Git/GitHub record below is ahead of anything this session wrote to Jira. The next agent
with Jira access must confirm each ticket below is **Done** (merged; acceptance criteria
verified in the PR) and add the PR link if missing. Jira wins over this baton if a ticket
shows reopened or disputed acceptance criteria.

## Work completed since Codex's handover (PR #47, `004ed01`)

| Ticket  | PR  | Merge     | Summary                                                                                             |
| ------- | --- | --------- | --------------------------------------------------------------------------------------------------- |
| KAN-123 | #48 | `70ff16d` | Verified Firebase claims enforced at the server boundary; `email-verified` cookie no longer trusted |
| KAN-154 | #49 | `7bf19af` | Profile Email label linked to its input; readonly preserved                                         |
| KAN-167 | #50 | `edfcfc6` | Configurable dev/E2E ports for parallel worktrees                                                   |
| KAN-155 | #51 | `3db1452` | App validation message for invalid profile website URL                                              |
| KAN-163 | #52 | `4d12a55` | Login history recorded only for explicit sign-ins, not session refresh                              |
| KAN-166 | #53 | `e726052` | Unused `verifyAdminAuth` helper removed                                                             |
| KAN-168 | #54 | `557c2bf` | ID token revocation checked on sign-in and refresh                                                  |
| KAN-128 | #55 | `3950bf1` | Stripe webhook returns 5xx on failure; idempotent by event id with a processing lease               |
| KAN-127 | #56 | `0456b1a` | Stripe checkout/billing-portal return URLs built server-side (open redirect)                        |
| KAN-126 | #58 | `0267038` | Profile actions select only safe fields                                                             |
| KAN-129 | #57 | `e3c735f` | Generic auth action errors; wildcard-CORS webhook `OPTIONS` removed (test pins it)                  |

KAN-129 review (security + TypeScript reviewers): no CRITICAL/HIGH. Non-blocking follow-ups
recorded on PR #57: `logger.error` receives whole Firebase/Prisma error objects with no
redaction (may write emails/uids to `logs/`); `catch (error: any)` remains in
`verifyTokenAction`/`getCurrentSessionAction`; `logError` test assertions do not check
arguments. Rate limiting is deferred to KAN-34; other actions still returning raw
`error.message` fall under KAN-31 (see `docs/developer/known-issues.md`).

Earlier completed work includes KAN-25–39, 111–113, 121–122, 130, 132–136, 138, 140–141,
144, 146–148, 153, 159, 161 and 162. See live Jira rather than this abbreviated history.

## Next: owner decision

The PM/Architect bug queue (KAN-154, 123, 155, 163) is done. Remaining candidates:

- **KAN-137:** evidence reconciliation between already-fixed backend code and legacy paths.
  No prerequisite; low risk.
- **KAN-125:** TOTP must be challenged during sign-in (KAN-39 only added setup).
  Security-sensitive; needs PM, Architect and Security review.
- **KAN-160:** collect its five review items before pickup.
- **KAN-124:** depends on backend admin work.
- Possible new story (propose to owner, do not widen KAN-129): redact error objects in
  server-side auth logging.

Keep stale KAN-3 open unless the owner explicitly decides otherwise. The owner authorized
**two developer agents with separate file/branch ownership**; one coordinator owns the baton
and Claude and Codex must not develop concurrently. Use read-only PM/Architect/Security
reviewers. Pick only eligible To-do tickets; update Jira before coding; one ticket per branch.

## E2E decision and limitations

The owner explicitly said **legacy browser only** and rejected an emulator plan. KAN-162
uses the dedicated `storecart-test` Firebase project and test PostgreSQL configuration in
gitignored `.env.e2e.local`, with isolated throwaway accounts and finally cleanup. See
[legacy-browser-regressions.md](../../docs/developer/legacy-browser-regressions.md).

These browser tests exercise the **legacy frontend**, not KAN-37–39 FastAPI paths until
KAN-41 cutover. Avatar upload is still a placeholder. TOTP setup does not protect sign-in.
KAN-157 needs test-mode webhook routing; KAN-158's discounted yearly price is an owner action.

`E2E_ENABLED` remains **false**, as set by the owner. Do not enable it automatically. Merge on
the green **CI gate** plus required reviews; the browser CI job is skipped, so PRs #48–#58
were not run through browser CI.

## Owner actions and architectural boundaries

- **KAN-145 remains held:** no public template export/first push without explicit go;
  show the file list before any authorized first push. Capacitor remains in StoreCart.
- **KAN-115** latency spike only when the owner says ready.
- Never operate on production Neon. Alembic owns `storecart_platform`; no build runs
  migrations. Production deploys only through the release workflow. Frontend Prisma
  remains source of truth until KAN-41; backend is an internal Vercel service (ADR-011).
- Owner must provision Upstash Redis production URL/token before release; production
  startup requires them. Optional Sentry project/DSN remains an owner action.
- Backend auth also requires `BACKEND_INTERNAL_KEY`, independent `RATE_LIMIT_EMAIL_KEY`
  and Firebase Admin project/client email/private key. Frontend and backend share the
  internal service key; current/next rotation is supported. See `backend-auth.md`.
- `TOTP_ENCRYPTION_KEY` must be a separate securely stored Fernet key for TOTP use.
  Missing key returns 503; invalid configured key prevents startup. Preserve it across
  deployments: replacing it without ciphertext migration breaks enrollments.
- Account deletion is not atomic across Firebase and SQL. SQL failure after Firebase
  deletion leaves a residual row requiring controlled operator repair. See `backend-profile.md`.
- No secrets or real env files in commits; no force push/history rewrite/`--no-verify`;
  do not lower coverage thresholds or silently skip failing tests.

## Local state and operational notes

Use the primary repository. Preserve untracked `.agents/`, `.claude/PRPs/`,
`.claude/plans/kan113-runs.md`, `.claude/progress/KAN-138-e2e.md`,
`.claude/progress/KAN-147.md` and `.claude/worktrees/`. Never commit the generated ignored
frontend `AGENTS.md`.

`.claude/worktrees/` holds many agent worktrees from earlier sessions (for example
`agent-a7df6e5880f1679fe` on the merged `fix/KAN-129-auth-error-messages`). Published
commits and primary `main` are authoritative; none of them holds unfinished assigned work.
Clean them up only with the owner's agreement.
