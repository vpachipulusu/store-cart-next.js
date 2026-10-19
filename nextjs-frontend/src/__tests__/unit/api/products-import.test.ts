// @vitest-environment node
/** KAN-74: the import wrapper posts the file as multipart to the store-scoped route and checks the body. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import { importStoreProducts } from '@/lib/api/products';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const STORE = 'store1';
const file = () => new File(['title,sku,price_minor\nA,A-1,1\n'], 'p.csv', { type: 'text/csv' });

describe('importStoreProducts', () => {
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

  it('posts the file as multipart and returns the outcome', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ imported: 1, product_ids: ['p1'], errors: [], truncated: false })
    );

    const result = await importStoreProducts(STORE, file());

    expect(result).toEqual({ success: true, data: { imported: 1, errors: [], truncated: false } });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe(`/v1/stores/${STORE}/products/import`);
    expect(request.headers.get('content-type')).toMatch(/^multipart\/form-data; boundary=/);
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    const sent = await request.formData();
    expect(await (sent.get('file') as File).text()).toContain('A,A-1,1');
  });

  it('returns row problems as data', async () => {
    const errors = [{ row: 2, column: 'price_minor', message: 'Price must be a whole number' }];
    fetchMock.mockResolvedValue(
      jsonResponse({ imported: 0, product_ids: [], errors, truncated: true })
    );

    expect(await importStoreProducts(STORE, file())).toEqual({
      success: true,
      data: { imported: 0, errors, truncated: true },
    });
  });

  it('refuses a body of the wrong shape', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ imported: '1', errors: [] }));

    expect(await importStoreProducts(STORE, file())).toEqual({
      success: false,
      error: 'The request failed. Please try again.',
      status: 502,
    });
  });

  it('passes a backend failure through with its status', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'Store not found' }, 404));

    expect(await importStoreProducts(STORE, file())).toEqual({
      success: false,
      error: 'Store not found',
      status: 404,
    });
  });
});
