// @vitest-environment node
/** KAN-50: the settings wrapper returns the platform currency code and fails loudly otherwise. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// `server-only` is mocked globally in vitest.setup.ts, so the wrapper imports fine here.
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: vi.fn() })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import { CURRENCY_CACHE_TTL_MS, CURRENCY_LOOKUP_FAILED_MESSAGE } from '@/lib/api/settings';

// A fresh module per test, so the in-memory cache never leaks between tests.
const loadFetchPlatformCurrency = async () => {
  vi.resetModules();
  return (await import('@/lib/api/settings')).fetchPlatformCurrency;
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('fetchPlatformCurrency', () => {
  let fetchPlatformCurrency: () => Promise<string>;
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    vi.stubGlobal('fetch', fetchMock);
    fetchPlatformCurrency = await loadFetchPlatformCurrency();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('returns the currency code and sends the internal key', async () => {
    fetchMock.mockResolvedValue(json({ success: true, data: { currency: 'EUR' } }));

    await expect(fetchPlatformCurrency()).resolves.toBe('EUR');
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/settings/currency');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('does not forward the session cookie', async () => {
    const get = vi.fn(() => ({ value: 'user-session' }));
    const { cookies } = await import('next/headers');
    vi.mocked(cookies).mockResolvedValueOnce({ get } as never);
    fetchMock.mockResolvedValue(json({ success: true, data: { currency: 'EUR' } }));

    await fetchPlatformCurrency();

    expect(get).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][0].headers.get('X-Session-Token')).toBeNull();
  });

  it('passes an abort signal so a stalled backend cannot hang', async () => {
    fetchMock.mockResolvedValue(json({ success: true, data: { currency: 'EUR' } }));
    await fetchPlatformCurrency();
    expect(fetchMock.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
  });

  it.each([{ currency: 5 }, { currency: '' }, {}])('rejects a malformed body %j', async (data) => {
    fetchMock.mockResolvedValue(json({ success: true, data }));
    await expect(fetchPlatformCurrency()).rejects.toThrow(CURRENCY_LOOKUP_FAILED_MESSAGE);
  });

  it('throws on a backend error status', async () => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'nope' }, 500));
    await expect(fetchPlatformCurrency()).rejects.toThrow(CURRENCY_LOOKUP_FAILED_MESSAGE);
  });

  it('throws when the backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    await expect(fetchPlatformCurrency()).rejects.toThrow(CURRENCY_LOOKUP_FAILED_MESSAGE);
  });

  it('serves a cached code within the TTL and refetches after it', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ success: true, data: { currency: 'EUR' } }))
      .mockResolvedValueOnce(json({ success: true, data: { currency: 'GBP' } }));

    await expect(fetchPlatformCurrency()).resolves.toBe('EUR');
    await expect(fetchPlatformCurrency()).resolves.toBe('EUR');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(CURRENCY_CACHE_TTL_MS + 1);
    await expect(fetchPlatformCurrency()).resolves.toBe('GBP');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not cache a failure', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ success: false, error: 'nope' }, 500))
      .mockResolvedValueOnce(json({ success: true, data: { currency: 'EUR' } }));

    await expect(fetchPlatformCurrency()).rejects.toThrow(CURRENCY_LOOKUP_FAILED_MESSAGE);
    await expect(fetchPlatformCurrency()).resolves.toBe('EUR');
  });

  it('shares one backend request between concurrent callers', async () => {
    fetchMock.mockResolvedValue(json({ success: true, data: { currency: 'EUR' } }));

    const codes = await Promise.all([fetchPlatformCurrency(), fetchPlatformCurrency()]);

    expect(codes).toEqual(['EUR', 'EUR']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
