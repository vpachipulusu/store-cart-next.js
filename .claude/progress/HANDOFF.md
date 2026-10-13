# HANDOFF: baton between Claude and Codex

Read `AGENTS.md` and [agent-handover.md](../../docs/developer/agent-handover.md) first.
This baton is the durable communication record; neither agent can read the other's chat.

| Field              | Value                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| owner              | **claude**, at the owner's request; effective once this handover is merged                            |
| ticket             | none active; next bug priorities KAN-154 and KAN-123                                                  |
| branch             | start from safely updated `main` in `C:\MainData\AI-Projects\store-cart-next.js`                      |
| last completed SHA | `df0acfeee87baf74d7793f243da2e1ac9b9f9495` (PR #46, KAN-162)                                          |
| handover revision  | resolve using Git history for this file; do not embed a self-referential SHA                          |
| open PRs           | no feature PR at this checkpoint; recheck GitHub and ensure this handover is on main                  |
| status             | primary tracked tree clean; completed code/tests committed and published; unrelated scratch preserved |
| blockers           | KAN-145 held; KAN-115 only when owner is ready; production configuration actions below                |
| updated            | 2026-10-13 by codex (Europe/London)                                                                   |

Codex stops developer mutations after publishing this transfer. A usage-limit reset
does not transfer ownership. When the owner requests return to Codex, finish a clean,
published checkpoint, record exact ticket/branch/SHA/PR/checks/blockers here and in
Jira, transfer the baton to `codex`, and give the owner a startup prompt.

## Work completed since Claude's latest handback

Claude's handback was PR #42 (`e440dd4afaa43e5d388c1d0396922610f5315063`).
Do not repeat already completed foundation work; Jira wins if an older plan differs.

- **KAN-37:** PR [#43](https://github.com/vpachipulusu/store-cart-next.js/pull/43),
  merge `0a7748f629e46877cacc98b51995578c4a914347`. Firebase backend session
  create/verify/revoke, internal-key rotation, verified claims, HMAC email limiting,
  trusted client-IP forwarding, generated contracts and corrected SDK envelope typing.
  144 backend tests passed (98.78% coverage), 149 frontend unit tests passed.
- **KAN-38:** PR [#44](https://github.com/vpachipulusu/store-cart-next.js/pull/44),
  merge `430de9fc543b03f2ad0ca49f057df2da39654b94`. Seven `/v1/me` operations:
  profile GET/PATCH, avatar PATCH, settings GET/PATCH, history GET and account DELETE.
  Safe fields, partial updates, bounded history, fresh same-UID reauthentication and
  OWNER deletion rejection. 239 backend tests passed (98.87% coverage).
- **KAN-39:** PR [#45](https://github.com/vpachipulusu/store-cart-next.js/pull/45),
  merge `f6c16dbfafc4655293da6bcc31fb081000563fb0`. Encrypted backend TOTP
  enrollment/verification/disablement, optional backend-only Fernet configuration,
  authenticated wiring and generated client. 283 combined backend tests passed
  (98.63% coverage). **This does not enforce TOTP during sign-in**; KAN-125 remains open.
- **KAN-162:** PR [#46](https://github.com/vpachipulusu/store-cart-next.js/pull/46).
  Eight new real legacy Playwright journeys plus three setup checks: **11 passed in
  44.2 seconds**, no skips. Ten cleanup/verification unit tests passed. Account
  deletion checks Firebase/database absence before teardown, so cleanup cannot hide
  an incomplete deletion. Specs join the existing baseline selection.
- **KAN-130:** reconciled as already fixed by `4a303da` (KAN-146); the unauthenticated
  logging route was removed, with no replacement. Jira evidence/status updated;
  no invented implementation patch.

Required CI gates and appropriate reviews passed before merging. Coverage floors
remain unchanged (backend 84.13%; frontend ratchet unchanged). Ordinary frontend
lint still has existing warnings; no new errors were accepted. No production Neon
operation or production release was performed.

Earlier completed work includes KAN-25–36, 111–113, 121–122, 132–136, 138, 140–141,
144, 146–148, 153, 159 and 161. See live Jira rather than this abbreviated history.

## Next bugs: PM and Architect decision

The owner requested bugs after E2E completion, then requested this Claude handover.
PM and Architect agree on the following queue; no bug implementation is half-done.

1. **KAN-154:** fix the profile Email label association and preserve readonly behavior.
   Check all profile field names; run the existing two failing baseline tests without
   changing their assertions. This is a confirmed accessibility defect with no
   backend prerequisite.
2. **KAN-123:** enforce verified Firebase claims at the **actual legacy protected
   server boundary**, including revocation checks. A forged, stale or missing
   `email-verified` cookie must not authorize an unverified user. Only remove the
   proxy cookie gate after authoritative protection and negative tests exist.
   Backend KAN-37 guards alone do not prove legacy frontend protection. Keep this
   independent of KAN-41 migration; require PM, Architect and Security review.
3. **KAN-155:** website native URL validation blocks the application's message.
   It touches the same profile file as KAN-154, so sequence it afterward.
4. **KAN-163:** duplicate login-history rows from legacy token refresh. Real browser
   evidence showed three rows after two explicit sign-ins. `onIdTokenChanged` in
   `use-session-refresh.ts` calls `verifyTokenAction`, which records history each time.
   Investigate with KAN-41; KAN-162 asserts growth/persistence, not deduplication.

KAN-124 depends on backend admin work. KAN-125 needs a sign-in challenge, not another
setup endpoint. KAN-126/129/137 require evidence reconciliation between already-fixed
backend code and remaining legacy paths. KAN-160 needs its five review items collected
before pickup. Keep stale KAN-3 open unless the owner explicitly decides otherwise.

The owner authorized **two developer agents with separate file/branch ownership**.
One coordinator owns the baton; Claude and Codex must not develop concurrently.
Use read-only PM/Architect/Security reviewers. Retain the owner's Claude model
preferences (Sonnet developers, Haiku PM where configured). Pick only eligible To-do
tickets; update Jira before coding and keep one ticket per branch.

## E2E decision and limitations

The owner explicitly said **legacy browser only** and rejected an emulator plan.
No emulator or backend HTTP harness was added. KAN-162 uses the dedicated
`storecart-test` Firebase project and dedicated test PostgreSQL configuration in
gitignored `.env.e2e.local`, with isolated throwaway accounts and finally cleanup.
See [legacy-browser-regressions.md](../../docs/developer/legacy-browser-regressions.md).

These browser tests exercise the **legacy frontend**, not KAN-37–39 FastAPI paths
until KAN-41 cutover. Avatar upload is still a placeholder. TOTP setup does not
protect sign-in. The full baseline was not claimed green from this focused run.
KAN-154–158 retain their separate issues; KAN-157 needs test-mode webhook routing,
and KAN-158's discounted yearly price is an owner action.

`E2E_ENABLED` remains **false**, as set by the owner. Do not enable it automatically.
Merge on the green **CI gate** plus required reviews; do not wait for the disabled
browser CI job. All Codex-owned verification servers are stopped at this handoff.

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

Use the primary repository, not the projectless Codex workspace. Preserve untracked
`.agents/`, `.claude/PRPs/`, `.claude/plans/kan113-runs.md`,
`.claude/progress/KAN-138-e2e.md`, `.claude/progress/KAN-147.md` and `.claude/worktrees/`.
Never commit the generated ignored frontend `AGENTS.md`.

Codex-created manual worktrees under the chat's `work/kan39` and `work/kan162` are
implementation/checking checkouts, not independent active tickets. Published commits
and primary main are authoritative. No unfinished feature is assigned to those paths.

Codex's Windows sandbox sometimes blocked Git's shell, uv cache locks, Node temp files
or async test sockets. Connected GitHub tools published exact trees verified against
local `git write-tree`; do not ask the owner to repeat `gh auth login` for that sandbox
issue. Claude should check its own auth/tools without printing credentials. Local
checks used workspace caches/temp directories and approved execution when needed.
