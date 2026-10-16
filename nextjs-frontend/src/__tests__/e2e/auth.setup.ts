import { mkdirSync } from 'node:fs';
import path from 'node:path';
import e2eEnv from '../../../scripts/e2e-env.cjs';
import { test as setup } from './helpers/fixtures';
import {
  STORAGE_STATE,
  TEST_ADMIN,
  TEST_USER,
  ensureAccountHasStore,
  loginViaUI,
} from './helpers/e2e-utils';

/**
 * Global setup for Playwright tests (KAN-113). Runs before every browser project.
 *
 * 1. Fails fast, naming the missing variables, when the e2e Firebase config (test project) is incomplete.
 * 2. Checks the app is reachable.
 * 3. Logs in through the UI ONCE per role and saves the session to playwright/.auth/<role>.json (gitignored).
 *    Specs reuse it with `test.use({ storageState: STORAGE_STATE.<role> })`, so they do not log in themselves.
 *    If Firebase Email/Password sign-in is disabled, this fails with a clear message instead of every login test
 *    timing out.
 */

setup('verify e2e environment', async ({ page }) => {
  e2eEnv.assertE2eFirebaseEnv(process.env, { requireAdmin: true });

  const response = await page.goto('/');
  if (!response || !response.ok()) {
    throw new Error(
      `App not reachable at ${process.env.E2E_BASE_URL ?? 'http://localhost:3000'}. Status: ${response?.status()}`
    );
  }
});

const ROLES = [
  {
    role: 'user',
    account: TEST_USER,
    envName: 'TEST_USER_EMAIL',
    configured: Boolean(process.env.TEST_USER_EMAIL),
  },
  {
    role: 'admin',
    account: TEST_ADMIN,
    envName: 'TEST_ADMIN_EMAIL',
    configured: Boolean(process.env.TEST_ADMIN_EMAIL),
  },
] as const;

for (const { role, account, envName, configured } of ROLES) {
  setup(`log in once as ${role}`, async ({ page }) => {
    setup.skip(!configured, `${envName} not configured; run \`npm run test:setup\``);

    // Fails with a clear message if Firebase Email/Password sign-in is disabled.
    await loginViaUI(page, account.email, account.password);

    // The shared user needs a store: without one /dashboard redirects to onboarding (KAN-210).
    // A missing BACKEND_INTERNAL_KEY fails here with a clear message instead of skipping the seed.
    if (role === 'user') {
      await ensureAccountHasStore(page, 'e2e-shared-user');
    }

    const statePath = STORAGE_STATE[role];
    mkdirSync(path.dirname(statePath), { recursive: true });
    await page.context().storageState({ path: statePath });
  });
}
