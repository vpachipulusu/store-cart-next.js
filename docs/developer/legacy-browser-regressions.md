# Legacy browser regression journeys

KAN-162 adds focused Playwright browser journeys for the user-facing auth, profile,
settings and TOTP flows corresponding to KAN-37–39. They use the existing Next.js
application, dedicated test Firebase project and dedicated test PostgreSQL database.
There is no emulator or mocked backend harness.

These journeys exercise the **legacy frontend implementation**. They do not prove
that the new FastAPI endpoints run until KAN-41 switches the frontend to FastAPI.
TOTP setup is covered; TOTP enforcement during sign-in is outside this scope.

| Spec                        | Browser assertions                                                                                                                                                                                                                                             |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `account-lifecycle.spec.ts` | Session survives reload; logout denies protected routes; profile edits persist and preserve other fields; fresh sign-in adds exactly one successful, persisted history row; exact deletion confirmation removes the disposable account and denies later access |
| `settings-totp.spec.ts`     | All four preferences persist after reload; invalid TOTP code is rejected; valid code enables setup, reload hides the enrollment secret, and valid-code disabling persists; avatar selection reports the existing placeholder                                   |

Avatar upload is not implemented in the current UI. Its test explicitly checks the
placeholder notification, rather than claiming upload or avatar persistence.
Login history asserts exactly one new record per explicit sign-in. Session refresh
(`refreshSessionAction`, used by the token-refresh hook and the verify-email re-check) mints the
cookie without recording history, fixed in [KAN-163](https://storecart.atlassian.net/browse/KAN-163).

## Isolation and cleanup

Every new journey creates a fresh `throwawayAccount` and uses real browser interactions.
The existing fixture deletes it in `finally`; mutations never affect the shared role
accounts. Test-only rate-limit identities use the existing local E2E build override.
The account-deletion journey verifies Firebase and database absence before teardown,
so automatic cleanup cannot hide a logout-only implementation. Cleanup ignores only
Firebase's already-missing-user error and propagates other Firebase/database failures.
Unit tests verify those cleanup guarantees and reject non-throwaway identities.

## Focused execution

From `nextjs-frontend/`, prepare the existing guarded `.env.e2e.local` with the dedicated
test services, then build and start the E2E app:

```powershell
npm run test:e2e:build
node scripts/e2e-start.mjs
```

In a second terminal in that directory:

```powershell
$env:E2E_REUSE_SERVER = '1'
npx playwright test --config playwright.baseline.config.ts account-lifecycle.spec.ts settings-totp.spec.ts --project chromium --workers 2
```

The new specs are included in the existing baseline's spec selection. The repository
variable `E2E_ENABLED` remains unchanged; adding these tests does not enable the
disabled CI browser job. Report focused results separately from the full baseline,
which retains its tracked KAN-154–158 issues (all Done; see local-e2e.md for the current quarantine list).
