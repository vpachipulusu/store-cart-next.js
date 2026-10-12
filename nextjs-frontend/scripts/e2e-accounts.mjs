/**
 * e2e account helpers (KAN-113), shared by scripts/setup-e2e-accounts.mjs and the Playwright throwaway-user fixture.
 *
 * Every account is created in the Firebase TEST project through the Admin SDK, using the e2e env only
 * (scripts/e2e-env.cjs), and in the local Postgres. Only accounts whose email matches E2E_EMAIL can be touched, so a
 * real user can never be reset or deleted. Nothing here prints a credential.
 */
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { cert, deleteApp, getApps, initializeApp } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { PrismaClient } from '@prisma/client';

/** user/admin: the shared role accounts. temp: throwaway accounts for state-changing tests, deleted afterwards. */
export const E2E_EMAIL = /^e2e-(user|admin|temp)-[0-9a-f]{12}@example\.com$/;
/** Marks the accounts for cleanup (KAN-131). */
const E2E_CLAIMS = { e2e: true };
const LOCAL_DB_HOSTS = new Set(['localhost', '127.0.0.1', '::1', 'db']);
const E2E_ADMIN_APP_NAME = 'e2e-accounts';

export const randomSuffix = () => randomBytes(6).toString('hex');
export const randomPassword = () => randomBytes(24).toString('base64url');

/** Throws unless DATABASE_URL points at a local database. */
export function assertLocalDatabase(env) {
  const url = env.DATABASE_URL;
  const host = url ? new URL(url).hostname : '';
  if (!LOCAL_DB_HOSTS.has(host)) {
    throw new Error(`Refusing to run: DATABASE_URL must point at a local database, not "${host || 'unset'}".`);
  }
}

/** Firebase Admin and Prisma clients for the e2e env. Call `close()` when done. */
export function openE2eAccountClients(env) {
  assertLocalDatabase(env);
  const app =
    getApps().find((existing) => existing.name === E2E_ADMIN_APP_NAME) ??
    initializeApp(
      {
        credential: cert({
          projectId: env.FIREBASE_ADMIN_PROJECT_ID,
          clientEmail: env.FIREBASE_ADMIN_CLIENT_EMAIL,
          privateKey: env.FIREBASE_ADMIN_PRIVATE_KEY.replace(/\\n/g, '\n'),
        }),
      },
      E2E_ADMIN_APP_NAME
    );
  const prisma = new PrismaClient({ datasources: { db: { url: env.DATABASE_URL } } });
  return {
    auth: getAuth(app),
    prisma,
    close: async () => {
      await prisma.$disconnect();
      await deleteApp(app);
    },
  };
}

function assertE2eEmail(email) {
  if (!E2E_EMAIL.test(email)) {
    throw new Error(`Refusing to touch "${email}": e2e accounts must match ${E2E_EMAIL}`);
  }
}

async function findUserByEmail(auth, email) {
  try {
    return await auth.getUserByEmail(email);
  } catch (error) {
    if (error?.code === 'auth/user-not-found') return null;
    throw error;
  }
}

/** Create the Firebase user, or reset its password; email verified, e2e claim set. */
export async function ensureFirebaseUser(auth, email, password, displayName) {
  assertE2eEmail(email);
  const existing = await findUserByEmail(auth, email);
  const user = existing
    ? await auth.updateUser(existing.uid, { password, emailVerified: true })
    : await auth.createUser({ email, password, emailVerified: true, displayName });
  await auth.setCustomUserClaims(user.uid, { ...(user.customClaims ?? {}), ...E2E_CLAIMS });
  return user;
}

/** Create or reset the app's users row (free tier, active) and its settings row. */
export async function ensureDbUser(prisma, firebaseUser, displayName) {
  assertE2eEmail(firebaseUser.email);
  // The local database is shared with dev. An e2e row created for the same email under another Firebase project
  // (before e2e moved to storecart-test) is re-linked to this project's uid instead of failing on the unique email.
  await prisma.user.updateMany({
    where: { email: firebaseUser.email, NOT: { firebaseUid: firebaseUser.uid } },
    data: { firebaseUid: firebaseUser.uid },
  });
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

/** A fresh free-tier account for one test. Delete it with deleteThrowawayAccount. */
export async function createThrowawayAccount({ auth, prisma }) {
  const email = `e2e-temp-${randomSuffix()}@example.com`;
  const password = randomPassword();
  const firebaseUser = await ensureFirebaseUser(auth, email, password, 'E2E Temp');
  await ensureDbUser(prisma, firebaseUser, 'E2E Temp');
  return { email, password, uid: firebaseUser.uid };
}

/** Delete a throwaway account from Firebase and Postgres (related rows cascade). */
export async function deleteThrowawayAccount({ auth, prisma }, account) {
  if (!/^e2e-temp-/.test(account.email)) {
    throw new Error(`Refusing to delete "${account.email}": only e2e-temp accounts are throwaway.`);
  }
  assertE2eEmail(account.email);
  await prisma.user.deleteMany({ where: { firebaseUid: account.uid } });
  await auth.deleteUser(account.uid);
}

/**
 * Set `updates` in a dotenv file, replacing those keys and keeping every other line. Values are never printed.
 */
export function updateEnvFileKeys(file, updates, header) {
  const lines = existsSync(file) ? readFileSync(file, 'utf8').split(/\r?\n/) : [];
  const seen = new Set();
  const updated = lines.map((line) => {
    const key = /^([A-Za-z0-9_]+)=/.exec(line)?.[1];
    if (key && Object.hasOwn(updates, key)) {
      seen.add(key);
      return `${key}=${updates[key]}`;
    }
    return line;
  });
  while (updated.length > 0 && updated[updated.length - 1] === '') updated.pop();
  const added = Object.keys(updates).filter((key) => !seen.has(key));
  if (added.length > 0) {
    updated.push(...(header ? [header] : []), ...added.map((key) => `${key}=${updates[key]}`));
  }
  // mode only applies on POSIX, when the file is first created; the file is gitignored either way.
  writeFileSync(file, `${updated.join('\n')}\n`, { mode: 0o600 });
}
