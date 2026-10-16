/**
 * e2e account helpers (KAN-113), shared by scripts/setup-e2e-accounts.mjs and the Playwright throwaway-user fixture.
 * Every account is created in the Firebase TEST project through the Identity Toolkit admin REST API, using the e2e env only
 * (scripts/e2e-env.cjs). The backend creates the matching users row on the first login. Only accounts whose
 * email matches E2E_EMAIL can be touched, so a real user can never be reset or deleted. Nothing here prints a
 * credential.
 */
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createFirebaseRestAdmin } from './firebase-rest-admin.mjs';

/**
 * user/admin: the shared role accounts. temp: throwaway accounts for state-changing tests, deleted afterwards.
 */
export const E2E_EMAIL = /^e2e-(user|admin|temp)-[0-9a-f]{12}@example\.com$/;
/** Marks the accounts for cleanup (KAN-131). */
const E2E_CLAIMS = { e2e: true };

export const randomSuffix = () => randomBytes(6).toString('hex');
export const randomPassword = () => randomBytes(24).toString('base64url');

/**
 * Firebase Auth admin client for the e2e env (Identity Toolkit REST, no firebase-admin dependency, KAN-208).
 * Call `close()` when done.
 */
export function openE2eAccountClients(env) {
  return {
    auth: createFirebaseRestAdmin({
      projectId: env.FIREBASE_ADMIN_PROJECT_ID,
      clientEmail: env.FIREBASE_ADMIN_CLIENT_EMAIL,
      privateKey: env.FIREBASE_ADMIN_PRIVATE_KEY.replace(/\\n/g, '\n'),
    }),
    close: async () => {},
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

/** A fresh free-tier account for one test. Delete it with deleteThrowawayAccount. */
export async function createThrowawayAccount({ auth }) {
  const email = `e2e-temp-${randomSuffix()}@example.com`;
  const password = randomPassword();
  const firebaseUser = await ensureFirebaseUser(auth, email, password, 'E2E Temp');
  return { email, password, uid: firebaseUser.uid };
}

function assertThrowawayAccount(account) {
  if (!/^e2e-temp-/.test(account.email)) {
    throw new Error(`Refusing to delete "${account.email}": only e2e-temp accounts are throwaway.`);
  }
  assertE2eEmail(account.email);
}

/** Verify browser deletion before fixture cleanup can hide a residual account. */
export async function assertThrowawayAccountDeleted({ auth }, account) {
  assertThrowawayAccount(account);
  let missing = false;
  try {
    await auth.getUser(account.uid);
  } catch (error) {
    if (error?.code !== 'auth/user-not-found') throw error;
    missing = true;
  }
  if (!missing)
    throw new Error('The throwaway Firebase account still exists after browser deletion.');
}

/** Delete a throwaway account from Firebase (the backend row goes with the app's own account deletion). */
export async function deleteThrowawayAccount({ auth }, account) {
  assertThrowawayAccount(account);
  try {
    await auth.deleteUser(account.uid);
  } catch (error) {
    // Account-deletion journeys remove Firebase first; fixture cleanup is idempotent.
    if (error?.code !== 'auth/user-not-found') throw error;
  }
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
