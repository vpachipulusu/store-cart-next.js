/**
 * Minimal Firebase Auth admin client over the Identity Toolkit REST API, for the e2e account helpers only
 * (KAN-208). It replaces the `firebase-admin` package, which the frontend no longer depends on, and uses only
 * Node built-ins. It authenticates with the e2e service account (FIREBASE_ADMIN_* in the e2e env) through the
 * OAuth JWT-bearer flow. Errors carry the Admin SDK codes the callers already test for (`auth/user-not-found`).
 * Nothing here prints or logs a credential, a token or a response body.
 */
import { createSign } from 'node:crypto';

const TOKEN_URL = 'https://oauth2.googleapis.com/token';
const SCOPE = 'https://www.googleapis.com/auth/identitytoolkit';
const API_ROOT = 'https://identitytoolkit.googleapis.com/v1/projects';
const TOKEN_LIFETIME_SECONDS = 3600;
const TOKEN_REFRESH_MARGIN_MS = 60_000;

const base64url = (value) => Buffer.from(value).toString('base64url');

function firebaseError(code, message) {
  return Object.assign(new Error(message), { code });
}

function signServiceAccountJwt({ clientEmail, privateKey }, nowSeconds) {
  const header = base64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claims = base64url(
    JSON.stringify({
      iss: clientEmail,
      scope: SCOPE,
      aud: TOKEN_URL,
      iat: nowSeconds,
      exp: nowSeconds + TOKEN_LIFETIME_SECONDS,
    })
  );
  const signature = createSign('RSA-SHA256').update(`${header}.${claims}`).sign(privateKey);
  return `${header}.${claims}.${base64url(signature)}`;
}

/** An admin client for one Firebase project. `fetchImpl` is injectable for tests. */
export function createFirebaseRestAdmin(
  { projectId, clientEmail, privateKey },
  fetchImpl = globalThis.fetch
) {
  let token = null;

  async function accessToken() {
    if (token && token.expiresAt - TOKEN_REFRESH_MARGIN_MS > Date.now()) return token.value;
    const assertion = signServiceAccountJwt(
      { clientEmail, privateKey },
      Math.floor(Date.now() / 1000)
    );
    const response = await fetchImpl(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        assertion,
      }),
    });
    if (!response.ok) {
      throw firebaseError('auth/invalid-credential', `Service account token request failed (${response.status})`);
    }
    const body = await response.json();
    token = { value: body.access_token, expiresAt: Date.now() + body.expires_in * 1000 };
    return token.value;
  }

  async function call(path, payload) {
    const response = await fetchImpl(`${API_ROOT}/${encodeURIComponent(projectId)}/${path}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${await accessToken()}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      // Firebase's message (e.g. USER_NOT_FOUND) names the problem without echoing credentials.
      const message = (await response.json().catch(() => null))?.error?.message ?? '';
      if (message.startsWith('USER_NOT_FOUND')) {
        throw firebaseError('auth/user-not-found', 'There is no user record for that identifier.');
      }
      throw firebaseError('auth/internal-error', `Identity Toolkit ${path} failed (${response.status} ${message})`);
    }
    return response.json();
  }

  async function lookup(query) {
    const { users } = await call('accounts:lookup', query);
    const user = users?.[0];
    if (!user) throw firebaseError('auth/user-not-found', 'There is no user record for that identifier.');
    return toUserRecord(user);
  }

  return {
    getUserByEmail: (email) => lookup({ email: [email] }),
    getUser: (uid) => lookup({ localId: [uid] }),
    async createUser({ email, password, emailVerified, displayName }) {
      const { localId } = await call('accounts', { email, password, emailVerified, displayName });
      return this.getUser(localId);
    },
    async updateUser(uid, { password, emailVerified }) {
      await call('accounts:update', {
        localId: uid,
        ...(password === undefined ? {} : { password }),
        ...(emailVerified === undefined ? {} : { emailVerified }),
      });
      return this.getUser(uid);
    },
    async setCustomUserClaims(uid, claims) {
      await call('accounts:update', { localId: uid, customAttributes: JSON.stringify(claims) });
    },
    async deleteUser(uid) {
      await call('accounts:delete', { localId: uid });
    },
  };
}

function toUserRecord(user) {
  return {
    uid: user.localId,
    email: user.email,
    emailVerified: user.emailVerified === true,
    customClaims: user.customAttributes ? JSON.parse(user.customAttributes) : undefined,
  };
}
