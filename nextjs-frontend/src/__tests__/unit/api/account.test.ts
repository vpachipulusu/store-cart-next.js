// @vitest-environment node
/**
 * KAN-41: the account wrappers call the right backend routes with the session cookie, the internal key
 * and (for sign-in) the browser's user agent, and unwrap the success envelope.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  changeBackendPassword,
  createBackendSession,
  fetchLoginHistory,
  fetchProfile,
  fetchSessionStatus,
  patchAvatar,
  revokeBackendSession,
  toLoginHistoryEntry,
  toProfile,
  verifyBackendIdToken,
} from '@/lib/api/account';
import { INVALID_SESSION_CODE, readSessionStatus } from '@/lib/auth/verified-session';
import { INVALID_AUTHENTICATION_MESSAGE } from '@/lib/api/session-rejected';
import { readFileSync } from 'node:fs';
import path from 'node:path';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('account wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
  });

  it('createBackendSession posts the ID token with the browser user agent and returns the cookie', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { session_cookie: 'cookie', expires_in: 432000 } })
    );

    const result = await createBackendSession('id-token', 'Mozilla/5.0 test');

    expect(result).toEqual({
      success: true,
      data: { session_cookie: 'cookie', expires_in: 432000 },
    });
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/auth/session');
    expect(request.method).toBe('POST');
    expect(request.headers.get('User-Agent')).toBe('Mozilla/5.0 test');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(await request.json()).toEqual({ id_token: 'id-token' });
  });

  it('createBackendSession truncates an oversized user agent', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { session_cookie: 'c', expires_in: 1 } })
    );

    await createBackendSession('id-token', 'x'.repeat(2000));

    expect(fetchMock.mock.calls[0][0].headers.get('User-Agent')).toHaveLength(512);
  });

  it('fetchProfile forwards the session cookie as X-Session-Token', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: { id: 'u1' } }));

    const result = await fetchProfile();

    expect(result).toEqual({ success: true, data: { id: 'u1' } });
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/me');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
  });

  it('patchAvatar sends null to clear the avatar', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: { id: 'u1' } }));

    await patchAvatar(null);

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('PATCH');
    expect(await request.json()).toEqual({ avatar_url: null });
  });

  it('fetchLoginHistory passes limit and offset as query parameters', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { login_history: [], total_count: 0 } })
    );

    await fetchLoginHistory(25, 50);

    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/v1/me/login-history');
    expect(url.searchParams.get('limit')).toBe('25');
    expect(url.searchParams.get('offset')).toBe('50');
  });

  it('fetchSessionStatus GETs /v1/auth/session/status with the session cookie and internal key (KAN-208)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { uid: 'u1', email: 'a@b.test', email_verified: true } })
    );

    const result = await fetchSessionStatus();

    expect(result).toEqual({
      success: true,
      data: { uid: 'u1', email: 'a@b.test', email_verified: true },
    });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('GET');
    expect(request.url).toBe('http://backend.test/v1/auth/session/status');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('the invalid-session wording matches what the backend sends (KAN-208)', () => {
    const backend = readFileSync(
      path.resolve(__dirname, '../../../../../fastapi_backend/app/api/auth.py'),
      'utf8'
    );

    expect(backend).toContain('HTTPException(401, "' + INVALID_AUTHENTICATION_MESSAGE + '")');
  });

  it('a revoked session answered by the real backend body becomes the invalid-session error (KAN-208)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Invalid authentication' }, 401)
    );

    await expect(readSessionStatus()).rejects.toMatchObject({ code: INVALID_SESSION_CODE });
  });

  it('an outage answered by the backend is not an invalid-session error (KAN-208)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Service unavailable' }, 503)
    );

    const failure = await readSessionStatus().catch((error: Error) => error);

    expect(failure).toBeInstanceOf(Error);
    expect((failure as { code?: string }).code).toBeUndefined();
  });

  it('verifyBackendIdToken POSTs the token to /v1/auth/id-token/verify WITHOUT the session cookie (KAN-208)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { uid: 'u1', email: 'a@b.test', email_verified: false } })
    );

    await verifyBackendIdToken('the-id-token');

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(request.url).toBe('http://backend.test/v1/auth/id-token/verify');
    expect(request.headers.get('X-Session-Token')).toBeNull();
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(await request.json()).toEqual({ id_token: 'the-id-token' });
  });

  it('changeBackendPassword PUTs both secrets to /v1/me/password with the session cookie (KAN-208)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true }));

    await changeBackendPassword('fresh-id-token', 'new-password-1');

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('PUT');
    expect(request.url).toBe('http://backend.test/v1/me/password');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(await request.json()).toEqual({
      id_token: 'fresh-id-token',
      new_password: 'new-password-1',
    });
  });

  it('revokeBackendSession surfaces the status of a rejected session', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Invalid authentication' }, 401)
    );

    expect(await revokeBackendSession()).toEqual({
      success: false,
      error: 'Invalid authentication',
      status: 401,
    });
    expect(fetchMock.mock.calls[0][0].method).toBe('DELETE');
  });

  it('maps snake_case API fields to the camelCase the pages use', () => {
    expect(
      toProfile({
        id: 'u1',
        email: 'a@b.test',
        email_verified: true,
        two_factor_enabled: false,
        display_name: 'Ada',
        bio: null,
        avatar_url: null,
        location: null,
        website: null,
        phone_number: '123',
        created_at: '2026-01-01T00:00:00Z',
        is_admin: false,
        admin_role: null,
      })
    ).toMatchObject({ emailVerified: true, displayName: 'Ada', phoneNumber: '123' });
    expect(
      toLoginHistoryEntry({
        id: 'h1',
        ip_address: '1.2.3.4',
        user_agent: 'UA',
        location: null,
        login_at: '2026-01-01T00:00:00Z',
        successful: false,
      })
    ).toEqual({
      id: 'h1',
      ipAddress: '1.2.3.4',
      userAgent: 'UA',
      location: null,
      loginAt: '2026-01-01T00:00:00Z',
      successful: false,
    });
  });
});
