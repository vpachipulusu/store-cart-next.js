// @vitest-environment node
/**
 * KAN-208: plan prices come from the backend (GET /v1/settings/plan-prices) in minor units, are shown in major
 * units, fall back per price, are cached for an hour and never throw.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/logger', () => ({ logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: vi.fn() })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  FALLBACK_PLAN_PRICES,
  PLAN_PRICES_CACHE_TTL_MS,
  PLAN_PRICES_FAILURE_TTL_MS,
  type PlanPrices,
} from '@/lib/api/plan-prices';

// A fresh module per test, so the in-memory cache never leaks between tests.
const loadFetchPlanPrices = async () => {
  vi.resetModules();
  return (await import('@/lib/api/plan-prices')).fetchPlanPrices;
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const prices = (data: unknown) => json({ success: true, data });

describe('fetchPlanPrices', () => {
  let fetchPlanPrices: () => Promise<PlanPrices>;
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    vi.stubGlobal('fetch', fetchMock);
    fetchPlanPrices = await loadFetchPlanPrices();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('converts minor units to major units and sends the internal key without a session', async () => {
    fetchMock.mockResolvedValue(
      prices({
        pro: { monthly: 1900, yearly: 19000 },
        enterprise: { monthly: 4950, yearly: 49500 },
      })
    );

    await expect(fetchPlanPrices()).resolves.toEqual({
      pro: { monthly: 19, yearly: 190 },
      enterprise: { monthly: 49.5, yearly: 495 },
    });
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/settings/plan-prices');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBeNull();
    expect(request.signal).toBeInstanceOf(AbortSignal);
  });

  it('falls back per price: a null price is 0 and the others are kept', async () => {
    fetchMock.mockResolvedValue(
      prices({
        pro: { monthly: 1900, yearly: null },
        enterprise: { monthly: null, yearly: null },
      })
    );

    await expect(fetchPlanPrices()).resolves.toEqual({
      pro: { monthly: 19, yearly: 0 },
      enterprise: { monthly: 0, yearly: 0 },
    });
  });

  it.each([-5, '12', null])('treats the malformed amount %j as 0', async (bad) => {
    fetchMock.mockResolvedValue(
      prices({ pro: { monthly: bad, yearly: 1000 }, enterprise: { monthly: 0, yearly: 0 } })
    );

    const result = await fetchPlanPrices();

    expect(result.pro).toEqual({ monthly: 0, yearly: 10 });
  });

  it('caches a successful read for an hour, then reads again', async () => {
    fetchMock.mockImplementation(async () =>
      prices({ pro: { monthly: 1900, yearly: 0 }, enterprise: { monthly: 0, yearly: 0 } })
    );

    await fetchPlanPrices();
    await fetchPlanPrices();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(PLAN_PRICES_CACHE_TTL_MS + 1);
    await fetchPlanPrices();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shares one backend request between concurrent callers on a cold cache', async () => {
    fetchMock.mockImplementation(async () =>
      prices({ pro: { monthly: 100, yearly: 100 }, enterprise: { monthly: 100, yearly: 100 } })
    );

    await Promise.all([fetchPlanPrices(), fetchPlanPrices(), fetchPlanPrices()]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([500, 503, 429])(
    'falls back to all zeros when the backend answers %i',
    async (status) => {
      fetchMock.mockResolvedValue(json({ success: false, error: 'Request failed' }, status));

      await expect(fetchPlanPrices()).resolves.toEqual(FALLBACK_PLAN_PRICES);
    }
  );

  it('falls back to all zeros when the backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));

    await expect(fetchPlanPrices()).resolves.toEqual(FALLBACK_PLAN_PRICES);
  });

  it('remembers a failure only briefly, so an outage does not blank prices for an hour', async () => {
    fetchMock.mockResolvedValueOnce(json({ success: false, error: 'Request failed' }, 503));
    await fetchPlanPrices();
    await fetchPlanPrices();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValue(
      prices({ pro: { monthly: 1900, yearly: 0 }, enterprise: { monthly: 0, yearly: 0 } })
    );
    vi.advanceTimersByTime(PLAN_PRICES_FAILURE_TTL_MS + 1);

    await expect(fetchPlanPrices()).resolves.toMatchObject({ pro: { monthly: 19 } });
  });
});
