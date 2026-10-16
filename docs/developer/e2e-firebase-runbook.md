# E2E Firebase project runbook (KAN-131)

Goal: no e2e account lives in the production Firebase project, and the legacy ones are deleted (with their refresh tokens revoked) before launch. e2e runs on the dedicated Firebase project `storecart-test` (KAN-113, KAN-162).

## Which Firebase project is used where

| Where | Project | Where the values live |
|---|---|---|
| Local e2e (`npm run test:e2e:local`) | test | `.env.e2e.local` (gitignored): `NEXT_PUBLIC_FIREBASE_*` and `FIREBASE_ADMIN_*` of the test project |
| CI e2e job | test | GitHub environment `e2e-test`: the `E2E_*` secrets read by `.github/workflows/e2e.yml` |
| Vercel Preview (both services) | test | Vercel Preview environment of each project, see below |
| Production | production | Vercel Production environment of each project |
| Local development (`npm run dev`) | development / see open confirmation | `.env.local` |

A preview deployment is two services that must name the same Firebase project, or session verification fails:

- Frontend (Next.js project): `NEXT_PUBLIC_FIREBASE_*` of the test project, baked in at build time (changing them needs a new build).
- Backend (FastAPI project): `FIREBASE_ADMIN_PROJECT_ID`, `FIREBASE_ADMIN_CLIENT_EMAIL`, `FIREBASE_ADMIN_PRIVATE_KEY` of the same test project.

The e2e job refuses to run when the test project id equals the repository variable `PROD_FIREBASE_PROJECT_ID`.

## Open owner confirmation

Which project do the legacy e2e accounts live in? `testing.md` says the development project, the KAN-131 description says the current project that becomes production's. The purge tool does not guess: it acts on the project its credentials belong to, and `--project-id` must name that project. Confirm in the Firebase console (Authentication > Users, search `e2e-` and `testuser@`) which project holds them, and run the purge against that one. If they are in both the development and the production project, run it once per project.

## The tool

`fastapi_backend/commands/purge_legacy_e2e_accounts.py`. It needs no database. It reads `FIREBASE_ADMIN_*` from the environment of the shell you run it in.

Selection: an account is matched only if its email is e2e-shaped:

- `e2e-(user|admin|temp)-<12 hex>@example.com` (the generated accounts), or
- `testuser@example.com` (default of the removed `create-test-user.mjs`), or
- any `e2e-...@example.com` variant that also carries the `{e2e: true}` claim.

A claim alone, or an `e2e-` address on another domain, is never matched. It pages through every user before changing anything.

Default is a dry run: it prints the project id, a count and masked emails (`e2e-us***@example.com`). It never prints uids, full emails, tokens or keys. With `--execute --project-id <id>` it revokes each match's refresh tokens, then deletes it. `<id>` must equal the credential's project id, otherwise it refuses (exit 2). A missing account counts as already done, so a re-run is safe. Any other error stops it (exit 1) without printing details.

## Owner checklist

1. Confirm which project holds the legacy accounts (open confirmation above).
2. Set the repository variable `PROD_FIREBASE_PROJECT_ID` (GitHub > Settings > Secrets and variables > Actions > Variables) to the production project id.
3. Confirm the `e2e-test` environment secrets are the test project's (`E2E_NEXT_PUBLIC_FIREBASE_*`, `E2E_FIREBASE_ADMIN_*`).
4. Confirm the Vercel Preview environment of both the frontend and the backend project use the test project (table above). Redeploy previews after changing the frontend variables.
5. In a shell on your machine, export the target project's `FIREBASE_ADMIN_PROJECT_ID`, `FIREBASE_ADMIN_CLIENT_EMAIL` and `FIREBASE_ADMIN_PRIVATE_KEY` (from the secret store; do not write them to a file in the repo), then run the dry run from `fastapi_backend/`:

   ```bash
   uv run python -m commands.purge_legacy_e2e_accounts
   ```

6. Review the count and masked emails against the console. If anything is unexpected, stop and report it on KAN-131.
7. Run it for real, with the project id you confirmed:

   ```bash
   uv run python -m commands.purge_legacy_e2e_accounts --execute --project-id <project-id>
   ```

8. Verify in the console that no `e2e-` / `testuser@` accounts remain, then run the dry run again: it must report 0.
9. Rotate any service-account key that was shared between the e2e setup and the target project (create a new key, update the secret store and Vercel, delete the old key).
10. Re-run steps 5, 6 and 8 just before launch (the dry run must report 0), then confirm on KAN-131. The story stays open until you do.
