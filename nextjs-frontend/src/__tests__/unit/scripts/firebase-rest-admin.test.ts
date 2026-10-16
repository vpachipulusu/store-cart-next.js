// @vitest-environment node
/**
 * KAN-208: the e2e account tooling talks to Firebase through the Identity Toolkit REST API instead of the
 * firebase-admin package. Everything here uses a fake fetch and a throwaway RSA key; nothing touches Firebase.
 */
import { generateKeyPairSync } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { createFirebaseRestAdmin } from '../../../../scripts/firebase-rest-admin.mjs';

const { privateKey } = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
  publicKeyEncoding: { type: 'spki', format: 'pem' },
});

const ROOT = 'https://identitytoolkit.googleapis.com/v1/projects/test-project/';

const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function setup(handler: (path: string, payload: Record<string, unknown>) => Response) {
  const calls: { path: string; payload: Record<string, unknown>; auth: string | null }[] = [];
  const fetchImpl = vi.fn(async (url: string | URL, init?: RequestInit) => {
    const target = String(url);
    if (target === 'https://oauth2.googleapis.com/token') {
      return reply({ access_token: 'access-token', expires_in: 3600 });
    }
    const path = target.replace(ROOT, '');
    const payload = JSON.parse(String(init?.body));
    calls.push({ path, payload, auth: new Headers(init?.headers).get('Authorization') });
    return handler(path, payload);
  });
  const admin = createFirebaseRestAdmin(
    { projectId: 'test-project', clientEmail: 'svc@test-project.iam.example', privateKey },
    fetchImpl as unknown as typeof fetch
  );
  return { admin, calls, fetchImpl };
}

describe('createFirebaseRestAdmin', () => {
  it('signs a service-account JWT, exchanges it once and reuses the access token', async () => {
    const { admin, calls, fetchImpl } = setup(() =>
      reply({ users: [{ localId: 'u1', email: 'a@b.test' }] })
    );

    await admin.getUser('u1');
    await admin.getUser('u1');

    const tokenCalls = fetchImpl.mock.calls.filter(([url]) => String(url).includes('oauth2'));
    expect(tokenCalls).toHaveLength(1);
    const assertion = new URLSearchParams(String(tokenCalls[0][1]?.body)).get('assertion') ?? '';
    expect(assertion.split('.')).toHaveLength(3);
    expect(calls.every((call) => call.auth === 'Bearer access-token')).toBe(true);
  });

  it('looks a user up by email and maps the record', async () => {
    const { admin, calls } = setup(() =>
      reply({
        users: [
          {
            localId: 'u1',
            email: 'e2e-temp-0123456789ab@example.com',
            emailVerified: true,
            customAttributes: JSON.stringify({ e2e: true }),
          },
        ],
      })
    );

    await expect(admin.getUserByEmail('e2e-temp-0123456789ab@example.com')).resolves.toEqual({
      uid: 'u1',
      email: 'e2e-temp-0123456789ab@example.com',
      emailVerified: true,
      customClaims: { e2e: true },
    });
    expect(calls[0]).toMatchObject({
      path: 'accounts:lookup',
      payload: { email: ['e2e-temp-0123456789ab@example.com'] },
    });
  });

  it('reports a missing user with the Admin SDK code callers test for', async () => {
    const { admin } = setup(() => reply({}));

    await expect(admin.getUser('missing')).rejects.toMatchObject({ code: 'auth/user-not-found' });
    await expect(admin.getUserByEmail('x@example.com')).rejects.toMatchObject({
      code: 'auth/user-not-found',
    });
  });

  it('maps USER_NOT_FOUND on delete to auth/user-not-found', async () => {
    const { admin } = setup(() => reply({ error: { message: 'USER_NOT_FOUND' } }, 400));

    await expect(admin.deleteUser('gone')).rejects.toMatchObject({ code: 'auth/user-not-found' });
  });

  it('turns any other failure into auth/internal-error without echoing a token', async () => {
    const { admin } = setup(() => reply({ error: { message: 'QUOTA_EXCEEDED' } }, 429));

    const failure = await admin.deleteUser('u1').catch((error: Error) => error);

    expect(failure).toMatchObject({ code: 'auth/internal-error' });
    expect((failure as Error).message).not.toContain('access-token');
  });

  it('creates a verified user and reads it back', async () => {
    const { admin, calls } = setup((path) =>
      path === 'accounts'
        ? reply({ localId: 'u2' })
        : reply({ users: [{ localId: 'u2', email: 'n@example.com', emailVerified: true }] })
    );

    const user = await admin.createUser({
      email: 'n@example.com',
      password: 'pw',
      emailVerified: true,
      displayName: 'N',
    });

    expect(user.uid).toBe('u2');
    expect(calls[0]).toMatchObject({
      path: 'accounts',
      payload: { email: 'n@example.com', emailVerified: true, displayName: 'N' },
    });
  });

  it('updates a password and sets custom claims as a JSON string', async () => {
    const { admin, calls } = setup(() => reply({ users: [{ localId: 'u1', email: 'a@b.test' }] }));

    await admin.updateUser('u1', { password: 'new', emailVerified: true });
    await admin.setCustomUserClaims('u1', { e2e: true });

    expect(calls[0]).toMatchObject({
      path: 'accounts:update',
      payload: { localId: 'u1', password: 'new', emailVerified: true },
    });
    expect(calls.find((c) => 'customAttributes' in c.payload)?.payload).toEqual({
      localId: 'u1',
      customAttributes: JSON.stringify({ e2e: true }),
    });
  });

  it('fails clearly when the service account token request is refused', async () => {
    const fetchImpl = vi.fn(async () => reply({ error: 'invalid_grant' }, 400));
    const admin = createFirebaseRestAdmin(
      { projectId: 'p', clientEmail: 'svc@p.iam.example', privateKey },
      fetchImpl as unknown as typeof fetch
    );

    await expect(admin.getUser('u1')).rejects.toMatchObject({ code: 'auth/invalid-credential' });
  });
});
