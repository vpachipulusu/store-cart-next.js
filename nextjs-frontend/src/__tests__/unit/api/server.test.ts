// @vitest-environment node
import { beforeEach, afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

vi.mock('server-only', () => ({}));

const cookieGet = vi.fn();
const headerGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: headerGet })),
}));

import { healthCheck, createSession, readSession } from '@/lib/api/generated';
import {
  BACKEND_ERROR_MESSAGE,
  BACKEND_UNAVAILABLE_MESSAGE,
  SESSION_HEADER,
  INTERNAL_KEY_HEADER,
  callBackend,
} from '@/lib/api/server';

const BACKEND_URL = 'http://backend.test';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('callBackend', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    process.env.BACKEND_API_URL = `${BACKEND_URL}/`;
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
    headerGet.mockReset();
    delete process.env.BACKEND_API_URL;
  });

  describe('Given a signed-in request', () => {
    it('forwards the trusted Vercel IP only alongside the internal key', async () => {
      vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
      vi.stubEnv('VERCEL', '1');
      headerGet.mockReturnValue('192.0.2.1');
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
      await callBackend((client) => healthCheck({ client }));
      expect(headerGet).toHaveBeenCalledWith('x-vercel-forwarded-for');
      expect(fetchMock.mock.calls[0][0].headers.get('X-Client-IP')).toBe('192.0.2.1');
    });

    it('ignores forwarded IPs outside Vercel and rejects malformed Vercel IPs', async () => {
      vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
      vi.stubEnv('VERCEL', '');
      headerGet.mockReturnValue('192.0.2.1');
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
      await callBackend((client) => healthCheck({ client }));
      expect(fetchMock.mock.calls[0][0].headers.has('X-Client-IP')).toBe(false);
      expect(headerGet).not.toHaveBeenCalled();
      vi.stubEnv('VERCEL', '1');
      headerGet.mockReturnValue('192.0.2.1, 192.0.2.2');
      await callBackend((client) => healthCheck({ client }));
      expect(fetchMock.mock.calls[1][0].headers.has('X-Client-IP')).toBe(false);
    });
    it('forwards only the current server-only internal key', async () => {
      vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-only-key');
      vi.stubEnv('BACKEND_INTERNAL_KEY_NEXT', 'next-key');
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
      await callBackend((client) => healthCheck({ client }));
      expect(fetchMock.mock.calls[0][0].headers.get(INTERNAL_KEY_HEADER)).toBe('server-only-key');
      expect(fetchMock.mock.calls[0][0].headers.get('X-Internal-Key-Next')).toBeNull();
    });
    it('forwards the session cookie in X-Session-Token and calls BACKEND_API_URL', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      const result = await callBackend((client) => healthCheck({ client }));

      const request = fetchMock.mock.calls[0][0];
      expect(request.url).toBe(`${BACKEND_URL}/health`);
      expect(request.headers.get(SESSION_HEADER)).toBe('firebase-session-cookie');
      expect(request.headers.get('cookie')).toBeNull();
      expect(result).toEqual({ success: true, data: { status: 'ok' } });
    });
  });

  describe('Given the withSession option', () => {
    it.each([{}, { withSession: true }])('sends the session header for %j', async (options) => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      await callBackend((client) => healthCheck({ client }), options);

      expect(fetchMock.mock.calls[0][0].headers.get(SESSION_HEADER)).toBe(
        'firebase-session-cookie'
      );
    });

    it('omits the session header and never reads cookies with withSession: false', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      await callBackend((client) => healthCheck({ client }), { withSession: false });

      expect(cookieGet).not.toHaveBeenCalled();
      expect(fetchMock.mock.calls[0][0].headers.has(SESSION_HEADER)).toBe(false);
    });
  });

  describe('Given no session cookie', () => {
    it('sends no session header', async () => {
      cookieGet.mockReturnValue(undefined);
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      await callBackend((client) => healthCheck({ client }));

      expect(fetchMock.mock.calls[0][0].headers.has(SESSION_HEADER)).toBe(false);
    });
  });

  describe('Given a backend body wrapped in the success envelope', () => {
    it('unwraps the generated session response with the matching inferred payload type', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({
          success: true,
          data: {
            session_cookie: 'returned-cookie',
            expires_in: 432000,
          },
        })
      );
      const result = await callBackend((client) =>
        createSession({ client, body: { id_token: 'id-token' } })
      );
      expect(result).toEqual({
        success: true,
        data: { session_cookie: 'returned-cookie', expires_in: 432000 },
      });
      if (result.success) {
        expectTypeOf(result.data.session_cookie).toEqualTypeOf<string>();
        expectTypeOf(result.data.expires_in).toEqualTypeOf<number>();
      }
    });

    it('unwraps the generated identity response with its inferred payload type', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({
          success: true,
          data: {
            uid: 'uid',
            email: 'ada@example.com',
            email_verified: true,
          },
        })
      );
      const result = await callBackend((client) => readSession({ client }));
      if (result.success) expectTypeOf(result.data.uid).toEqualTypeOf<string>();
      expect(result).toEqual({
        success: true,
        data: { uid: 'uid', email: 'ada@example.com', email_verified: true },
      });
    });
    it('unwraps data', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ success: true, data: { status: 'ok' } }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: true, data: { status: 'ok' } });
    });
  });

  describe('Given the backend error envelope', () => {
    it('returns the backend error message', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'Invalid request' }, 422));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: 'Invalid request', status: 422 });
    });

    it('returns a generic message when the body is not the envelope', async () => {
      fetchMock.mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: BACKEND_ERROR_MESSAGE, status: 502 });
    });

    it('treats an error status with an empty body as a failure', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 500 }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: BACKEND_ERROR_MESSAGE, status: 500 });
    });
  });

  describe('Given the backend is unreachable', () => {
    it('returns an unavailable error instead of throwing', async () => {
      fetchMock.mockRejectedValue(new TypeError('fetch failed'));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: BACKEND_UNAVAILABLE_MESSAGE });
    });
  });

  describe('Given BACKEND_API_URL is not set', () => {
    it('fails fast with a clear message', async () => {
      delete process.env.BACKEND_API_URL;

      await expect(callBackend((client) => healthCheck({ client }))).rejects.toThrow(
        'BACKEND_API_URL is not set'
      );
    });

    it('marks the error so sign-in can report an outage (KAN-241)', async () => {
      delete process.env.BACKEND_API_URL;

      await expect(callBackend((client) => healthCheck({ client }))).rejects.toMatchObject({
        code: 'backend/not-configured',
      });
    });
  });

  describe('Given BACKEND_INTERNAL_KEY is not set (KAN-241)', () => {
    it('fails fast with the marked error when the route requires the key', async () => {
      vi.stubEnv('BACKEND_INTERNAL_KEY', '');

      await expect(
        callBackend((client) => healthCheck({ client }), { requireInternalKey: true })
      ).rejects.toMatchObject({
        code: 'backend/not-configured',
        message: 'BACKEND_INTERNAL_KEY is not set',
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('still calls public routes without the key', async () => {
      vi.stubEnv('BACKEND_INTERNAL_KEY', '');
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result.success).toBe(true);
    });
  });
});
