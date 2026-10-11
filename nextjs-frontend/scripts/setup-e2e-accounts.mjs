#!/usr/bin/env node
/**
 * Create or refresh the e2e test user and test admin (KAN-113). Run with `npm run test:setup`.
 *
 * - Emails are unguessable and passwords are random. Both are written only to .env.e2e.local (gitignored, read by
 *   playwright.config.ts) and are never printed.
 * - Re-running reuses the stored credentials and resets the Firebase passwords to match them.
 * - The admin gets today's admin model: an AdminUser row with role super_admin in the local Postgres.
 *
 * These accounts live in the Firebase project that will also be production's. KAN-131 moves them to a separate
 * project and deletes them before launch.
 */
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { cert, initializeApp } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { PrismaClient } from '@prisma/client';
import dotenv from 'dotenv';

const E2E_ENV_FILE = '.env.e2e.local';
const REQUIRED_ENV = ['FIREBASE_ADMIN_PROJECT_ID', 'FIREBASE_ADMIN_CLIENT_EMAIL', 'FIREBASE_ADMIN_PRIVATE_KEY'];

dotenv.config({ path: '.env.local' });
dotenv.config();

const missing = REQUIRED_ENV.filter((name) => !process.env[name]);
if (missing.length > 0) {
  console.error(`Missing environment variables: ${missing.join(', ')}`);
  process.exit(1);
}

const randomSuffix = () => randomBytes(6).toString('hex');
const randomPassword = () => randomBytes(24).toString('base64url');

function loadOrCreateCredentials() {
  const stored = existsSync(E2E_ENV_FILE) ? dotenv.parse(readFileSync(E2E_ENV_FILE)) : {};
  const credentials = {
    TEST_USER_EMAIL: stored.TEST_USER_EMAIL || `e2e-user-${randomSuffix()}@example.com`,
    TEST_USER_PASSWORD: stored.TEST_USER_PASSWORD || randomPassword(),
    TEST_ADMIN_EMAIL: stored.TEST_ADMIN_EMAIL || `e2e-admin-${randomSuffix()}@example.com`,
    TEST_ADMIN_PASSWORD: stored.TEST_ADMIN_PASSWORD || randomPassword(),
  };
  const body = Object.entries(credentials)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
  writeFileSync(E2E_ENV_FILE, `# e2e test accounts (KAN-113). Generated; do not commit.\n${body}\n`, {
    mode: 0o600,
  });
  return credentials;
}

async function ensureFirebaseUser(auth, email, password, displayName) {
  try {
    const existing = await auth.getUserByEmail(email);
    return auth.updateUser(existing.uid, { password, emailVerified: true, disabled: false });
  } catch (error) {
    if (error?.code !== 'auth/user-not-found') throw error;
    return auth.createUser({ email, password, emailVerified: true, displayName });
  }
}

async function ensureDbUser(prisma, firebaseUser, displayName) {
  const user = await prisma.user.upsert({
    where: { firebaseUid: firebaseUser.uid },
    update: { email: firebaseUser.email, emailVerified: true, subscriptionTier: 'free', subscriptionStatus: 'active' },
    create: {
      firebaseUid: firebaseUser.uid,
      email: firebaseUser.email,
      emailVerified: true,
      displayName,
      subscriptionTier: 'free',
      subscriptionStatus: 'active',
    },
  });
  await prisma.userSettings.upsert({ where: { userId: user.id }, update: {}, create: { userId: user.id } });
  return user;
}

async function main() {
  const credentials = loadOrCreateCredentials();
  const auth = getAuth(
    initializeApp({
      credential: cert({
        projectId: process.env.FIREBASE_ADMIN_PROJECT_ID,
        clientEmail: process.env.FIREBASE_ADMIN_CLIENT_EMAIL,
        privateKey: process.env.FIREBASE_ADMIN_PRIVATE_KEY.replace(/\\n/g, '\n'),
      }),
    })
  );
  const prisma = new PrismaClient();

  try {
    const testUser = await ensureFirebaseUser(
      auth,
      credentials.TEST_USER_EMAIL,
      credentials.TEST_USER_PASSWORD,
      'E2E User'
    );
    await ensureDbUser(prisma, testUser, 'E2E User');

    const testAdmin = await ensureFirebaseUser(
      auth,
      credentials.TEST_ADMIN_EMAIL,
      credentials.TEST_ADMIN_PASSWORD,
      'E2E Admin'
    );
    const adminDbUser = await ensureDbUser(prisma, testAdmin, 'E2E Admin');
    await prisma.adminUser.upsert({
      where: { userId: adminDbUser.id },
      update: { role: 'super_admin', permissions: ['*'] },
      create: { userId: adminDbUser.id, role: 'super_admin', permissions: ['*'] },
    });

    console.log(`e2e test user and admin are ready; credentials are in ${E2E_ENV_FILE}.`);
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((error) => {
  console.error(`e2e account setup failed: ${error?.code ?? ''} ${error?.message ?? error}`);
  process.exit(1);
});
