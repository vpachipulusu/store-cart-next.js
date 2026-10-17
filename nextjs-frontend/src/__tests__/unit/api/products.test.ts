// @vitest-environment node
/** KAN-73: the products wrapper calls the store-scoped product API with the session and curates errors. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  addProductVariant,
  createStoreProduct,
  deleteProductImage,
  deleteProductVariant,
  deleteStoreProduct,
  fetchCategories,
  fetchProduct,
  fetchProducts,
  loadCategoryList,
  productErrorMessage,
  updateProductVariant,
  updateStoreProduct,
  PRODUCT_FORBIDDEN_MESSAGE,
  PRODUCT_RATE_LIMITED_MESSAGE,
  PRODUCT_REQUEST_FAILED_MESSAGE,
  PRODUCT_SESSION_MESSAGE,
  PRODUCT_UNAVAILABLE_MESSAGE,
} from '@/lib/api/products';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const STORE = 'store1';
const PRODUCT = 'prod1';

describe('products API wrapper', () => {
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

  it('lists products with the filters, paging and credentials', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ data: [], currency: 'GBP', total: 0, limit: 25, offset: 50 })
    );

    const result = await fetchProducts(STORE, { status: 'active', categoryId: 'cat1', offset: 50 });

    expect(result).toEqual({
      success: true,
      data: { data: [], currency: 'GBP', total: 0, limit: 25, offset: 50 },
    });
    const request = fetchMock.mock.calls[0][0];
    const url = new URL(request.url);
    expect(url.pathname).toBe(`/v1/stores/${STORE}/products`);
    expect(url.searchParams.get('status')).toBe('active');
    expect(url.searchParams.get('category_id')).toBe('cat1');
    expect(url.searchParams.get('limit')).toBe('25');
    expect(url.searchParams.get('offset')).toBe('50');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
  });

  it('unwraps a product read', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: PRODUCT, title: 'Tee' } }));
    const result = await fetchProduct(STORE, PRODUCT);
    expect(result).toEqual({ success: true, data: { id: PRODUCT, title: 'Tee' } });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe(
      `/v1/stores/${STORE}/products/${PRODUCT}`
    );
  });

  it.each([
    ['create', () => createStoreProduct(STORE, { title: 'Tee', variants: [] }), 'POST', ''],
    [
      'update',
      () => updateStoreProduct(STORE, PRODUCT, { title: 'Tee 2' }),
      'PATCH',
      `/${PRODUCT}`,
    ],
    [
      'add variant',
      () => addProductVariant(STORE, PRODUCT, { sku: 'A', price_minor: 1 }),
      'POST',
      `/${PRODUCT}/variants`,
    ],
    [
      'update variant',
      () => updateProductVariant(STORE, PRODUCT, 'v1', { stock: 2 }),
      'PATCH',
      `/${PRODUCT}/variants/v1`,
    ],
    [
      'delete variant',
      () => deleteProductVariant(STORE, PRODUCT, 'v1'),
      'DELETE',
      `/${PRODUCT}/variants/v1`,
    ],
    [
      'delete image',
      () => deleteProductImage(STORE, PRODUCT, 'i1'),
      'DELETE',
      `/${PRODUCT}/images/i1`,
    ],
    ['delete product', () => deleteStoreProduct(STORE, PRODUCT), 'DELETE', `/${PRODUCT}`],
  ])('%s uses the right method and path', async (_name, call, method, suffix) => {
    fetchMock.mockResolvedValue(
      method === 'DELETE' && suffix === `/${PRODUCT}`
        ? new Response(null, { status: 204 })
        : jsonResponse({ data: { id: PRODUCT } })
    );

    const result = await call();

    expect(result.success).toBe(true);
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe(method);
    expect(new URL(request.url).pathname).toBe(`/v1/stores/${STORE}/products${suffix}`);
  });

  it('sends the typed body as JSON', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: PRODUCT } }));
    await updateProductVariant(STORE, PRODUCT, 'v1', { price_minor: 1250, stock: 3 });
    expect(await fetchMock.mock.calls[0][0].json()).toEqual({ price_minor: 1250, stock: 3 });
  });

  it('returns the backend status with a failed result', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'SKU already exists in this store' }, 409)
    );
    const result = await addProductVariant(STORE, PRODUCT, { sku: 'A', price_minor: 1 });
    expect(result).toEqual({
      success: false,
      error: 'SKU already exists in this store',
      status: 409,
    });
  });

  it('refuses a product body that is empty or not an object', async () => {
    fetchMock.mockResolvedValueOnce(new Response('null', { status: 200 }));
    expect(await fetchProduct(STORE, PRODUCT)).toMatchObject({ success: false, status: 502 });
    fetchMock.mockResolvedValueOnce(jsonResponse([1, 2]));
    expect(await fetchProduct(STORE, PRODUCT)).toMatchObject({ success: false, status: 502 });
  });

  it('reports an unreachable backend without a status', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    const result = await fetchProducts(STORE);
    expect(result.success).toBe(false);
    if (!result.success) expect(productErrorMessage(result)).toBe(PRODUCT_UNAVAILABLE_MESSAGE);
  });
});

describe('productErrorMessage', () => {
  it.each([404, 409, 422])('shows the curated backend text for %i', (status) => {
    expect(productErrorMessage({ error: 'Curated text', status })).toBe('Curated text');
  });

  it('falls back to a fixed message when a curated status has no text', () => {
    expect(productErrorMessage({ error: '', status: 422 })).toBe(PRODUCT_REQUEST_FAILED_MESSAGE);
  });

  it.each([
    [401, PRODUCT_SESSION_MESSAGE],
    [403, PRODUCT_FORBIDDEN_MESSAGE],
    [429, PRODUCT_RATE_LIMITED_MESSAGE],
    [503, PRODUCT_UNAVAILABLE_MESSAGE],
    [500, PRODUCT_REQUEST_FAILED_MESSAGE],
  ])('never forwards backend text for %i', (status, expected) => {
    expect(productErrorMessage({ error: 'internal detail: db password', status })).toBe(expected);
  });

  it('does not show the generic text of a raw FastAPI 422 as if it were curated', async () => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    const raw = vi.fn(async () =>
      jsonResponse(
        { detail: [{ loc: ['body', 'title'], msg: 'field required', type: 'missing' }] },
        422
      )
    );
    vi.stubGlobal('fetch', raw);
    const result = await addProductVariant(STORE, PRODUCT, { sku: 'A', price_minor: 1 });
    expect(result).toMatchObject({ success: false, status: 422 });
    if (!result.success) {
      expect(productErrorMessage(result)).toBe(PRODUCT_REQUEST_FAILED_MESSAGE);
    }
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('does not show an over-long backend text', () => {
    expect(productErrorMessage({ error: 'x'.repeat(201), status: 409 })).toBe(
      PRODUCT_REQUEST_FAILED_MESSAGE
    );
  });

  it('treats a missing status as unreachable', () => {
    expect(productErrorMessage({ error: 'x' })).toBe(PRODUCT_UNAVAILABLE_MESSAGE);
  });
});

describe('products API wrapper: search and categories', () => {
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

  const emptyList = { data: [], currency: 'GBP', total: 0, limit: 25, offset: 0 };
  const categories = {
    data: [{ id: 'c1', name: 'Mugs', slug: 'mugs', parent_id: null, position: 0 }],
    truncated: false,
  };

  it('sends the search text as q, with the other filters', async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyList));
    await fetchProducts(STORE, { search: 'blue tee', status: 'draft' });
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.searchParams.get('q')).toBe('blue tee');
    expect(url.searchParams.get('status')).toBe('draft');
  });

  it('leaves q out when there is no search', async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyList));
    await fetchProducts(STORE);
    expect(new URL(fetchMock.mock.calls[0][0].url).searchParams.has('q')).toBe(false);
  });

  it('refuses a list body that is not an object with a currency', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: [] }));
    const result = await fetchProducts(STORE);
    expect(result).toMatchObject({ success: false, status: 502 });
  });

  it('reads the category list of the store', async () => {
    fetchMock.mockResolvedValue(jsonResponse(categories));
    const result = await fetchCategories(STORE);
    expect(result).toEqual({ success: true, data: categories });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe(`/v1/stores/${STORE}/categories`);
  });

  it('treats a missing truncated flag as false and refuses a body without a data array', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    expect(await fetchCategories(STORE)).toEqual({
      success: true,
      data: { data: [], truncated: false },
    });
    fetchMock.mockResolvedValueOnce(jsonResponse({ nope: true }));
    expect(await fetchCategories(STORE)).toMatchObject({ success: false, status: 502 });
  });

  it('loadCategoryList returns rows and the flag, or null on any failure', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...categories, truncated: true }));
    expect(await loadCategoryList(STORE)).toEqual({ rows: categories.data, truncated: true });
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'x' }, 500));
    expect(await loadCategoryList(STORE)).toBeNull();
  });
});
