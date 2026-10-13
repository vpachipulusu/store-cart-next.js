#!/usr/bin/env node
/**
 * Create or refresh the e2e test user and test admin (KAN-113). Run with `npm run test:setup`.
 *
 * - Accounts are created in the Firebase TEST project (storecart-test) through the Admin SDK, using the e2e env only
 *   (scripts/e2e-env.cjs): the FIREBASE_ADMIN_* service account in .env.e2e.local, never the dev project in .env.local.
 * - The users rows (and the admin's AdminUser row) are created in the dedicated e2e database (DATABASE_URL in
 *   .env.e2e.local, never the dev database). Run `npm run test:e2e:db` first to apply the schema there.
 * - A fixed database-only Pro subscriber is seeded so the admin subscription pages always have a row to list.
 * - Emails are unguessable and passwords are random. Both are written only to .env.e2e.local (gitignored, read by
 *   playwright.config.ts) and are never printed. Only the TEST_* keys are updated; the rest of the file is kept.
 * - Re-running reuses the stored credentials and resets the Firebase passwords to match them.
 * - The admin gets today's admin model: an AdminUser row with role super_admin in the local Postgres.
 */
import dotenv from 'dotenv';
import { existsSync, readFileSync } from 'node:fs';
import e2eEnv from './e2e-env.cjs';
import {
  ensureDbUser,
  ensureFirebaseUser,
  ensureSeedSubscriber,
  openE2eAccountClients,
  randomPassword,
  randomSuffix,
  updateEnvFileKeys,
} from './e2e-accounts.mjs';

const { E2E_ENV_FILE, loadE2eEnv, assertE2eFirebaseEnv } = e2eEnv;

function loadOrCreateCredentials() {
  const stored = existsSync(E2E_ENV_FILE) ? dotenv.parse(readFileSync(E2E_ENV_FILE)) : {};
  const credentials = {
    TEST_USER_EMAIL: stored.TEST_USER_EMAIL || `e2e-user-${randomSuffix()}@example.com`,
    TEST_USER_PASSWORD: stored.TEST_USER_PASSWORD || randomPassword(),
    TEST_ADMIN_EMAIL: stored.TEST_ADMIN_EMAIL || `e2e-admin-${randomSuffix()}@example.com`,
    TEST_ADMIN_PASSWORD: stored.TEST_ADMIN_PASSWORD || randomPassword(),
  };
  updateEnvFileKeys(
    E2E_ENV_FILE,
    credentials,
    '# e2e test accounts (KAN-113). Generated; do not commit.'
  );
  return credentials;
}

async function main() {
  const env = loadE2eEnv();
  assertE2eFirebaseEnv(env, { requireAdmin: true });
  const credentials = loadOrCreateCredentials();
  const clients = openE2eAccountClients(env);

  try {
    const testUser = await ensureFirebaseUser(
      clients.auth,
      credentials.TEST_USER_EMAIL,
      credentials.TEST_USER_PASSWORD,
      'E2E User'
    );
    await ensureDbUser(clients.prisma, testUser, 'E2E User');

    const testAdmin = await ensureFirebaseUser(
      clients.auth,
      credentials.TEST_ADMIN_EMAIL,
      credentials.TEST_ADMIN_PASSWORD,
      'E2E Admin'
    );
    const adminDbUser = await ensureDbUser(clients.prisma, testAdmin, 'E2E Admin');
    await clients.prisma.adminUser.upsert({
      where: { userId: adminDbUser.id },
      update: { role: 'super_admin', permissions: ['*'] },
      create: { userId: adminDbUser.id, role: 'super_admin', permissions: ['*'] },
    });

    await ensureSeedSubscriber(clients.prisma);

    console.log(
      `e2e test user and admin are ready in Firebase project ${env.NEXT_PUBLIC_FIREBASE_PROJECT_ID}; ` +
        `credentials are in ${E2E_ENV_FILE}.`
    );
  } finally {
    await clients.close();
  }
}

main().catch((error) => {
  console.error(`e2e account setup failed: ${error?.code ?? ''} ${error?.message ?? error}`);
  process.exit(1);
});
