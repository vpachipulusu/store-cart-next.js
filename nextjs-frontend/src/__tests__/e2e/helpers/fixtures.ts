import { test as base, expect } from '@playwright/test';

/** Sentry ingest hosts (e.g. o123.ingest.de.sentry.io). */
const SENTRY_HOST = /^https:\/\/([a-z0-9-]+\.)*sentry\.io\//i;

export type ThrowawayAccount = { email: string; password: string; uid: string };

type AccountClients = {
  auth: unknown;
  prisma: unknown;
  close: () => Promise<void>;
};

type AccountsModule = {
  openE2eAccountClients: (env: NodeJS.ProcessEnv) => AccountClients;
  createThrowawayAccount: (clients: AccountClients) => Promise<ThrowawayAccount>;
  deleteThrowawayAccount: (clients: AccountClients, account: ThrowawayAccount) => Promise<void>;
};

// Loaded only by tests that use a throwaway account, so other specs do not load firebase-admin and Prisma.
const loadAccountsModule = (): Promise<AccountsModule> =>
  import('../../../../scripts/e2e-accounts.mjs') as Promise<AccountsModule>;

/**
 * Shared e2e fixtures. Import `test` and `expect` from here instead of '@playwright/test'.
 *
 * - Sentry: the e2e build runs with NEXT_PUBLIC_SENTRY_DSN unset (scripts/e2e-build.mjs), so the SDK is disabled.
 *   As a second guard every browser context aborts requests to Sentry, so e2e runs never report to the real Sentry
 *   project and a pending Sentry request can never hold a page open.
 * - throwawayAccount: a fresh free-tier account in the e2e Firebase project and the local database, deleted after
 *   the test. Use it for every test that logs out, revokes or expires a session, or changes plan or billing state,
 *   so the shared role sessions saved by auth.setup.ts are never affected. Log in with `loginAsThrowawayAccount`.
 */
export const test = base.extend<
  { throwawayAccount: ThrowawayAccount },
  { accountClients: AccountClients }
>({
  // The fixture callback is named `provide` (not Playwright's usual `use`) so the React hooks lint rule ignores it.
  context: async ({ context }, provide) => {
    await context.route(SENTRY_HOST, (route) => route.abort());
    await provide(context);
  },

  accountClients: [
    // eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for fixture dependencies
    async ({}, provide) => {
      const accounts = await loadAccountsModule();
      const clients = accounts.openE2eAccountClients(process.env);
      await provide(clients);
      await clients.close();
    },
    { scope: 'worker' },
  ],

  throwawayAccount: async ({ accountClients }, provide) => {
    const accounts = await loadAccountsModule();
    const account = await accounts.createThrowawayAccount(accountClients);
    try {
      await provide(account);
    } finally {
      await accounts.deleteThrowawayAccount(accountClients, account);
    }
  },
});

export { expect };
