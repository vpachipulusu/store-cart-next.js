// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('server-only', () => ({}));

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
}));

import { healthCheck } from '@/lib/api/generated';
import {
  BACKEND_ERROR_MESSAGE,
  BACKEND_UNAVAILABLE_MESSAGE,
  SESSION_HEADER,
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
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
    delete process.env.BACKEND_API_URL;
  });

  describe('Given a signed-in request', () => {
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

  describe('Given no session cookie', () => {
    it('sends no session header', async () => {
      cookieGet.mockReturnValue(undefined);
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));

      await callBackend((client) => healthCheck({ client }));

      expect(fetchMock.mock.calls[0][0].headers.has(SESSION_HEADER)).toBe(false);
    });
  });

  describe('Given a backend body wrapped in the success envelope', () => {
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

      expect(result).toEqual({ success: false, error: 'Invalid request' });
    });

    it('returns a generic message when the body is not the envelope', async () => {
      fetchMock.mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: BACKEND_ERROR_MESSAGE });
    });

    it('treats an error status with an empty body as a failure', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 500 }));

      const result = await callBackend((client) => healthCheck({ client }));

      expect(result).toEqual({ success: false, error: BACKEND_ERROR_MESSAGE });
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
  });
});
