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
  createBackendSession,
  fetchLoginHistory,
  fetchProfile,
  patchAvatar,
  revokeBackendSession,
  toLoginHistoryEntry,
  toProfile,
} from '@/lib/api/account';

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
