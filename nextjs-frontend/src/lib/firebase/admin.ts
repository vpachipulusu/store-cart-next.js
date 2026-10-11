import { initializeApp, getApps, cert, App } from 'firebase-admin/app';
import { getAuth, Auth } from 'firebase-admin/auth';

const CREDENTIAL_ENV_NAMES = [
  'FIREBASE_ADMIN_PROJECT_ID',
  'FIREBASE_ADMIN_CLIENT_EMAIL',
  'FIREBASE_ADMIN_PRIVATE_KEY',
] as const;

let adminAuth: Auth | null = null;

/**
 * Firebase Admin app, created on first use.
 *
 * Never initialise the Admin SDK at module scope: `next build` imports every route and server-action module while
 * collecting page data, so a module-scope `initializeApp(cert(...))` makes the build require the FIREBASE_ADMIN_*
 * secrets (KAN-136, same cause as KAN-134 for Stripe).
 */
export function getAdminApp(): App {
  const existing = getApps();
  if (existing.length > 0) {
    return existing[0];
  }

  const missing = CREDENTIAL_ENV_NAMES.filter((name) => !process.env[name]);
  if (missing.length > 0) {
    throw new Error(
      `Firebase Admin credentials are not configured. Missing: ${missing.join(', ')}. Please add them to your .env file.`
    );
  }

  return initializeApp({
    credential: cert({
      projectId: process.env.FIREBASE_ADMIN_PROJECT_ID,
      clientEmail: process.env.FIREBASE_ADMIN_CLIENT_EMAIL,
      privateKey: process.env.FIREBASE_ADMIN_PRIVATE_KEY?.replace(/\\n/g, '\n'),
    }),
  });
}

/**
 * Firebase Admin Auth, created on first use and reused afterwards.
 */
export function getAdminAuth(): Auth {
  if (!adminAuth) {
    adminAuth = getAuth(getAdminApp());
  }

  return adminAuth;
}
