# Security

**Last updated:** 2026-10-11

## Server actions are public endpoints

Every exported Next.js server action is a public POST endpoint. Anyone can call it with any argument, outside the UI. Route handlers are public in the same way.

- Authenticate and authorise **inside each action or handler**. Do not rely on the page or the UI.
- Never trust a client-supplied tier, role or plan. Read them from the verified session or the database.
- Validate every input with a schema (Zod in the frontend) before using it.
- Return the `{ success, data?, error? }` shape and do not leak internal errors.

The unauthenticated auth actions and the `/api/auth/signup`, `/api/auth/login` and `/api/auth/logout` route handlers are removed, and the client-supplied plan argument is gone. The `auth-actions-security` unit tests cover this.

## Server secrets and database access

- After Foundation, the frontend holds no `DATABASE_URL`, no Firebase Admin credentials, and no other server secrets. FastAPI owns them.
- Until then, the frontend still uses Prisma and server secrets. Do not add more.
- The frontend calls FastAPI from the server only, with the internal service key `BACKEND_INTERNAL_KEY`, sent as the `X-Internal-Key` header (ADR-003). The key is held only in the server environment of each Vercel project. Each environment (production, preview, development) has its own key.
- Open question: the service key is itself a server secret in the Next.js environment, and the done-check does not flag it. Decide before KAN-51 is closed whether it counts under the Foundation rule. See [known-issues.md](known-issues.md).

## Credentials

- Never print or commit credentials, tokens or keys. Do not paste them into Jira, PRs, chat, or logs.
- `.env`, `.env.local` and `.env*.local` are gitignored (root `.gitignore`). `.env.example` is the only committed env file, and it contains names and placeholders only.
- Store real values in the team's secret store. Validate required secrets at startup.
- If a secret is exposed, rotate it immediately.

## E2E test accounts

- `npm run test:setup` generates random emails and passwords, and writes them only to `.env.e2e.local`.
- The accounts live in the future production Firebase project until KAN-131 moves them to a separate project and deletes them before launch.
- The setup script refuses to run against a non-local `DATABASE_URL` and refuses to touch any account whose email does not match the generated pattern.

## Reporting a security issue

If you find an issue, stop, use the security review step in the team's rules, fix any critical issue before continuing, and review the codebase for similar problems.
