# Security

**Last updated:** 2026-10-12

## Server actions are public endpoints

Every exported Next.js server action is a public POST endpoint. Anyone can call it with any argument, outside the UI. Route handlers are public in the same way.

- Authenticate and authorise **inside each action or handler**. Do not rely on the page or the UI.
- Never trust a client-supplied tier, role or plan. Read them from the verified session or the database.
- Validate every input with a schema (Zod in the frontend) before using it.
- Return the `{ success, data?, error? }` shape and do not leak internal errors.

The unauthenticated auth actions and the `/api/auth/signup`, `/api/auth/login` and `/api/auth/logout` route handlers are removed, and the client-supplied plan argument is gone. The `auth-actions-security` unit tests cover this.

## Server secrets and database access

- After Foundation, the frontend holds no `DATABASE_URL`, no Firebase Admin credentials, and no other server secrets. FastAPI owns them.
- The frontend no longer has Prisma or a database (KAN-51). It no longer has the Firebase Admin SDK or Stripe either (KAN-208): ESLint blocks `stripe`, `firebase-admin`, `@/lib/firebase/admin` and `@/lib/stripe/server` everywhere, with no allow-list, and CI runs `npm run foundation:scan`.
- **Planned, not yet implemented:** the frontend calls FastAPI from the server only, with the internal service key `BACKEND_INTERNAL_KEY`, sent as the `X-Internal-Key` header (ADR-003). The key is held only in the project's server environment, a separate key per environment (ADR-011, ADR-003). On `main`, nothing in `fastapi_backend/app` checks this header, and the variable is not in `.env.example`.
- Open question: the service key is itself a server secret in the Next.js environment, and the done-check does not flag it. Decide before KAN-51 is closed whether it counts under the Foundation rule. See [known-issues.md](known-issues.md#open-questions).
- Never put a secret in a `NEXT_PUBLIC_*` variable; anything with that prefix is bundled into the browser.

## Credentials

- Never print or commit credentials, tokens or keys. Do not paste them into Jira, PRs, chat, or logs.
- `.env`, `.env.local` and `.env*.local` are gitignored (root `.gitignore`). `.env.example` is the only committed env file, and it contains names and placeholders only.
- Store real values in the team's secret store. Validate required secrets at startup.
- If a secret is exposed, rotate it immediately.

## E2E test accounts

- `npm run test:setup` generates random emails and passwords, and writes them only to `.env.e2e.local`.
- Since KAN-113 and KAN-162, e2e creates its accounts only in the separate test project `storecart-test`. Accounts created before that may still exist in an older project (which one is an open owner confirmation); KAN-131 deletes them with `commands.purge_legacy_e2e_accounts` before launch. See [e2e-firebase-runbook.md](e2e-firebase-runbook.md).
- The setup script refuses to run against a non-local `DATABASE_URL` and refuses to touch any account whose email does not match the generated pattern.

## Reporting a security issue

If you find an issue, stop, use the security review step in the team's rules, fix any critical issue before continuing, and review the codebase for similar problems.
