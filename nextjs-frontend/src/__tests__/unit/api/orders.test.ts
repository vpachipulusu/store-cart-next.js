// @vitest-environment node
/** KAN-79: the orders wrapper calls the store-scoped order API with the session and curates errors. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  fetchOrder,
  fetchOrders,
  fulfilStoreOrder,
  orderErrorMessage,
  ORDER_FORBIDDEN_MESSAGE,
  ORDER_RATE_LIMITED_MESSAGE,
  ORDER_REQUEST_FAILED_MESSAGE,
  ORDER_SESSION_MESSAGE,
  ORDER_UNAVAILABLE_MESSAGE,
} from '@/lib/api/orders';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const STORE = 'store1';
const ORDER = 'order1';
const order = { id: ORDER, status: 'paid', currency: 'GBP', items: [] };

describe('orders API wrapper', () => {
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

  it('lists orders with the status, paging and credentials', async () => {
    const body = { data: [], total: 0, limit: 25, offset: 50 };
    fetchMock.mockResolvedValue(jsonResponse(body));

    const result = await fetchOrders(STORE, { status: 'paid', offset: 50 });

    expect(result).toEqual({ success: true, data: body });
    const request = fetchMock.mock.calls[0][0];
    const url = new URL(request.url);
    expect(url.pathname).toBe(`/v1/stores/${STORE}/orders`);
    expect(url.searchParams.get('status')).toBe('paid');
    expect(url.searchParams.get('limit')).toBe('25');
    expect(url.searchParams.get('offset')).toBe('50');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
  });

  it('refuses a list body of the wrong shape', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));

    const result = await fetchOrders(STORE);

    expect(result).toEqual({
      success: false,
      error: ORDER_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });

  it('reads one order and unwraps the data envelope', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: order }));

    const result = await fetchOrder(STORE, ORDER);

    expect(result).toEqual({ success: true, data: order });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe(
      `/v1/stores/${STORE}/orders/${ORDER}`
    );
  });

  it('posts the tracking number and carrier to the fulfil route', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { ...order, status: 'fulfilled' } }));

    const result = await fulfilStoreOrder(STORE, ORDER, { trackingNumber: 'T-1', carrier: null });

    expect(result.success).toBe(true);
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe(`/v1/stores/${STORE}/orders/${ORDER}/fulfil`);
    expect(await request.json()).toEqual({ tracking_number: 'T-1', carrier: null });
  });

  it('keeps the curated backend message of a 409', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Only a paid order can be fulfilled' }, 409)
    );

    const result = await fulfilStoreOrder(STORE, ORDER, { trackingNumber: 'T-1', carrier: null });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.status).toBe(409);
      expect(orderErrorMessage(result)).toBe('Only a paid order can be fulfilled');
    }
  });

  it('reports a network failure without a status as unavailable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));

    const result = await fetchOrders(STORE);

    expect(result.success).toBe(false);
    if (!result.success) expect(orderErrorMessage(result)).toBe(ORDER_UNAVAILABLE_MESSAGE);
  });
});

describe('orderErrorMessage', () => {
  it.each([
    [401, ORDER_SESSION_MESSAGE],
    [403, ORDER_FORBIDDEN_MESSAGE],
    [429, ORDER_RATE_LIMITED_MESSAGE],
    [503, ORDER_UNAVAILABLE_MESSAGE],
    [500, ORDER_REQUEST_FAILED_MESSAGE],
  ])('maps %i to a fixed message and never forwards backend text', (status, expected) => {
    expect(orderErrorMessage({ error: 'psycopg2 stack trace', status })).toBe(expected);
  });

  it.each([404, 409, 422])('shows the curated text of a %i', (status) => {
    expect(orderErrorMessage({ error: 'Order not found', status })).toBe('Order not found');
  });

  it('does not show an over-long or empty message as curated', () => {
    expect(orderErrorMessage({ error: 'x'.repeat(300), status: 422 })).toBe(
      ORDER_REQUEST_FAILED_MESSAGE
    );
    expect(orderErrorMessage({ error: '', status: 404 })).toBe(ORDER_REQUEST_FAILED_MESSAGE);
  });
});
