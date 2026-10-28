// @vitest-environment node
/** KAN-96: the analytics wrapper calls the store-scoped analytics API with the session and curates errors. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  ANALYTICS_FORBIDDEN_MESSAGE,
  ANALYTICS_RATE_LIMITED_MESSAGE,
  ANALYTICS_REQUEST_FAILED_MESSAGE,
  ANALYTICS_SESSION_MESSAGE,
  ANALYTICS_UNAVAILABLE_MESSAGE,
  analyticsErrorMessage,
  fetchStoreAnalytics,
} from '@/lib/api/analytics';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const STORE = 'store1';
const report = {
  start_date: '2026-10-01',
  end_date: '2026-10-02',
  bucket: 'day',
  currencies: [
    {
      currency: 'GBP',
      totals: { orders: 1, gross_sales_minor: 100, refunds_minor: 0, net_sales_minor: 100 },
      series: [],
      top_products_by_revenue: [],
      top_products_by_units: [],
    },
  ],
};

describe('analytics API wrapper', () => {
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

  it('asks for the store, range and bucket with the credentials', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: report }));

    const result = await fetchStoreAnalytics(STORE, {
      from: '2026-10-01',
      to: '2026-10-02',
      bucket: 'week',
    });

    expect(result).toEqual({ success: true, data: report });
    const request = fetchMock.mock.calls[0][0];
    const url = new URL(request.url);
    expect(url.pathname).toBe(`/v1/stores/${STORE}/analytics`);
    expect(url.searchParams.get('from')).toBe('2026-10-01');
    expect(url.searchParams.get('to')).toBe('2026-10-02');
    expect(url.searchParams.get('bucket')).toBe('week');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
  });

  it('leaves out dates the page did not get, so the backend defaults apply', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: report }));

    await fetchStoreAnalytics(STORE, { bucket: 'day' });

    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.searchParams.has('from')).toBe(false);
    expect(url.searchParams.has('to')).toBe(false);
  });

  it.each([[{ data: { start_date: '2026-10-01' } }], [{ data: [] }], [[]], ['text']])(
    'refuses an unexpected body %j',
    async (body) => {
      fetchMock.mockResolvedValue(jsonResponse(body));

      const result = await fetchStoreAnalytics(STORE, { bucket: 'day' });

      expect(result).toEqual({
        success: false,
        error: ANALYTICS_REQUEST_FAILED_MESSAGE,
        status: 502,
      });
    }
  );

  it('passes the status of a refused call through', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'Forbidden' }, 403));

    const result = await fetchStoreAnalytics(STORE, { bucket: 'day' });

    expect(result).toMatchObject({ success: false, status: 403 });
  });
});

describe('analyticsErrorMessage', () => {
  it('shows the curated range message of a 422', () => {
    const error = 'The range can cover at most 366 days';
    expect(analyticsErrorMessage({ error, status: 422 })).toBe(error);
  });

  it.each([
    [{ error: 'x' }, ANALYTICS_UNAVAILABLE_MESSAGE],
    [{ error: 'Request failed', status: 422 }, ANALYTICS_REQUEST_FAILED_MESSAGE],
    [{ error: 'x'.repeat(201), status: 422 }, ANALYTICS_REQUEST_FAILED_MESSAGE],
    [{ error: 'x', status: 401 }, ANALYTICS_SESSION_MESSAGE],
    [{ error: 'x', status: 403 }, ANALYTICS_FORBIDDEN_MESSAGE],
    [{ error: 'x', status: 429 }, ANALYTICS_RATE_LIMITED_MESSAGE],
    [{ error: 'x', status: 503 }, ANALYTICS_UNAVAILABLE_MESSAGE],
    [{ error: 'Store not found', status: 404 }, ANALYTICS_REQUEST_FAILED_MESSAGE],
  ])('%j -> fixed message', (result, expected) => {
    expect(analyticsErrorMessage(result)).toBe(expected);
  });
});
