// @vitest-environment node
/**
 * KAN-73: the product pages scope every read to the selected store, validate query params before forwarding
 * them, page with the right offsets and show curated errors.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  fetchProducts: vi.fn(),
  fetchProduct: vi.fn(),
  loadCategoryList: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
  logError: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  notFound: mocks.notFound,
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/lib/api/products', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/products')>('@/lib/api/products');
  return {
    ...actual,
    fetchProducts: mocks.fetchProducts,
    fetchProduct: mocks.fetchProduct,
    loadCategoryList: mocks.loadCategoryList,
  };
});
vi.mock('@/components/dashboard/products/product-editor', () => ({
  ProductEditor: ({ initial }: { initial: { title: string } }) => (
    <div data-editor={initial.title} />
  ),
}));
vi.mock('@/components/dashboard/products/product-create-form', () => ({
  ProductCreateForm: ({ currency }: { currency: string }) => <div data-create={currency} />,
}));

import ProductsPage from '@/app/dashboard/products/page';
import NewProductPage from '@/app/dashboard/products/new/page';
import EditProductPage from '@/app/dashboard/products/[productId]/page';

const html = (node: React.ReactNode) => renderToStaticMarkup(node as React.ReactElement);
const ok = <T,>(data: T) => ({ success: true as const, data });
const listPage = async (params: Record<string, string | string[] | undefined> = {}) =>
  html(await ProductsPage({ searchParams: Promise.resolve(params) }));

const SUMMARY = {
  id: 'p1',
  title: 'Blue Tee',
  slug: 'blue-tee',
  status: 'active' as const,
  created_at: '2026-03-05T00:00:00Z',
  updated_at: '2026-03-06T00:00:00Z',
  variant_count: 2,
  min_price_minor: 1000,
  max_price_minor: 1500,
};

const list = (data: unknown[], total = data.length) =>
  ok({ data, currency: 'GBP', total, limit: 25, offset: 0 });

const CATEGORIES = {
  truncated: false,
  rows: [
    { id: 'c1', name: 'Clothing', slug: 'clothing', parent_id: null, position: 0 },
    { id: 'c2', name: 'Shirts', slug: 'shirts', parent_id: 'c1', position: 0 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getCurrentStoreSelection.mockResolvedValue({
    available: true,
    stores: [],
    selected: { id: 'store1', name: 'Acme Shop' },
  });
  mocks.fetchProducts.mockResolvedValue(list([SUMMARY]));
  mocks.loadCategoryList.mockResolvedValue(CATEGORIES);
});

describe('products list page', () => {
  it('lists the selected store products with prices in the store currency', async () => {
    const markup = await listPage();
    expect(mocks.fetchProducts).toHaveBeenCalledWith('store1', {
      search: undefined,
      status: undefined,
      categoryId: undefined,
      limit: 25,
      offset: 0,
    });
    expect(markup).toContain('Blue Tee');
    expect(markup).toContain('£10.00 – £15.00');
    expect(markup).toContain('Products for Acme Shop');
    expect(markup).toContain('href="/dashboard/products/new"');
  });

  it('forwards only valid filters and computes the offset from the page', async () => {
    await listPage({ status: 'draft', category: 'cat_1', page: '3' });
    expect(mocks.fetchProducts).toHaveBeenCalledWith('store1', {
      search: undefined,
      status: 'draft',
      categoryId: 'cat_1',
      limit: 25,
      offset: 50,
    });
  });

  it.each([
    { status: 'archived' },
    { status: ['draft', 'active'] },
    { category: '../etc' },
    { page: '-4' },
    { page: 'abc' },
  ])('ignores the bad param %j', async (params) => {
    await listPage(params);
    const [, query] = mocks.fetchProducts.mock.calls[0];
    expect(query.offset).toBe(0);
    expect(query.categoryId).toBeUndefined();
    if ('status' in params && params.status === 'archived') expect(query.status).toBeUndefined();
  });

  it('caps a huge page number', async () => {
    await listPage({ page: '99999999999' });
    expect(mocks.fetchProducts.mock.calls[0][1].offset).toBe(9_999 * 25);
  });

  it('shows an empty state for a store without products, and a filtered one differently', async () => {
    mocks.fetchProducts.mockResolvedValue(list([], 0));
    expect(await listPage()).toContain('No products yet.');
    expect(await listPage({ status: 'draft' })).toContain('No products match these filters.');
  });

  it('links to the neighbouring pages and shows the range', async () => {
    mocks.fetchProducts.mockResolvedValue(list([SUMMARY], 60));
    const markup = await listPage({ status: 'active', page: '2' });
    expect(markup).toContain('Showing 26 to 50 of 60');
    expect(markup).toContain('href="/dashboard/products?status=active"');
    expect(markup).toContain('href="/dashboard/products?status=active&amp;page=3"');
  });

  it('offers a way back when the page is past the end', async () => {
    mocks.fetchProducts.mockResolvedValue(list([], 10));
    expect(await listPage({ page: '9' })).toContain('Back to the first page');
  });

  it('shows a curated error with a Retry link and logs the status, not the body', async () => {
    mocks.fetchProducts.mockResolvedValue({
      success: false,
      error: 'secret db detail',
      status: 500,
    });
    const markup = await listPage({ status: 'draft' });
    expect(markup).toContain('The request failed. Please try again.');
    expect(markup).not.toContain('secret db detail');
    expect(markup).toContain('href="/dashboard/products?status=draft"');
    expect(mocks.logError).toHaveBeenCalledWith('Products page: list failed', { status: 500 });
  });

  it('renders nothing when the layout has no store to show', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({ available: false, error: 'x' });
    expect(await listPage()).toBe('');
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });
    expect(await listPage()).toBe('');
    expect(mocks.fetchProducts).not.toHaveBeenCalled();
  });
});

describe('new product page', () => {
  it('reads the store currency from the list response', async () => {
    mocks.fetchProducts.mockResolvedValue(list([], 0));
    const markup = html(await NewProductPage());
    expect(mocks.fetchProducts).toHaveBeenCalledWith('store1', { limit: 1 });
    expect(markup).toContain('data-create="GBP"');
  });

  it('shows a Retry link when the currency cannot be read', async () => {
    mocks.fetchProducts.mockResolvedValue({ success: false, error: 'x', status: 503 });
    const markup = html(await NewProductPage());
    expect(markup).toContain('href="/dashboard/products/new"');
    expect(markup).not.toContain('data-create');
  });
});

describe('edit product page', () => {
  const edit = async (productId: string) =>
    html(await EditProductPage({ params: Promise.resolve({ productId }) }));

  it('loads the product from the selected store', async () => {
    mocks.fetchProduct.mockResolvedValue(ok({ id: 'p1', title: 'Blue Tee' }));
    expect(await edit('p1')).toContain('data-editor="Blue Tee"');
    expect(mocks.fetchProduct).toHaveBeenCalledWith('store1', 'p1');
  });

  it('answers not found for a malformed id without calling the backend', async () => {
    await expect(edit('../x')).rejects.toThrow('NEXT_NOT_FOUND');
    expect(mocks.fetchProduct).not.toHaveBeenCalled();
  });

  it('answers not found for a product of another store (backend 404)', async () => {
    mocks.fetchProduct.mockResolvedValue({
      success: false,
      error: 'Product not found',
      status: 404,
    });
    await expect(edit('p9')).rejects.toThrow('NEXT_NOT_FOUND');
  });

  it('keeps an h1 on the error page', async () => {
    mocks.fetchProduct.mockResolvedValue({ success: false, error: 'x', status: 503 });
    expect(await edit('p1')).toContain('<h1');
  });

  it('shows a Retry link on other failures', async () => {
    mocks.fetchProduct.mockResolvedValue({ success: false, error: 'x', status: 503 });
    const markup = await edit('p1');
    expect(markup).toContain('href="/dashboard/products/p1"');
    expect(markup).toContain('could not be reached');
  });
});

describe('products list search and category filter', () => {
  it('forwards the trimmed search text and keeps it in the paging links', async () => {
    mocks.fetchProducts.mockResolvedValue(list([SUMMARY], 60));
    const markup = await listPage({ q: '  blue tee  ', page: '2' });
    expect(mocks.fetchProducts.mock.calls[0][1]).toMatchObject({ search: 'blue tee', offset: 25 });
    expect(markup).toContain('value="blue tee"');
    expect(markup).toContain('href="/dashboard/products?q=blue+tee&amp;page=3"');
  });

  it('cuts search text to the API maximum and ignores a blank one', async () => {
    await listPage({ q: 'x'.repeat(150) });
    expect(mocks.fetchProducts.mock.calls[0][1].search).toHaveLength(100);
    await listPage({ q: '   ' });
    expect(mocks.fetchProducts.mock.calls[1][1].search).toBeUndefined();
  });

  it('uses the first value of a repeated q parameter', async () => {
    await listPage({ q: ['mug', 'tee'] });
    expect(mocks.fetchProducts.mock.calls[0][1].search).toBe('mug');
  });

  it('offers categories by name as a tree and marks the chosen one', async () => {
    const markup = await listPage({ category: 'c2' });
    expect(markup).toContain('All categories');
    expect(markup).toContain('Clothing');
    expect(markup).toContain('— Shirts');
    expect(mocks.fetchProducts.mock.calls[0][1].categoryId).toBe('c2');
  });

  it('keeps a chosen category the list does not hold, and says no match for a search', async () => {
    mocks.fetchProducts.mockResolvedValue(list([], 0));
    const markup = await listPage({ q: 'zzz', category: 'gone' });
    expect(markup).toContain('Unknown category (gone)');
    expect(markup).toContain('No products match these filters.');
  });

  it('says Category not listed for a chosen category when the list is truncated', async () => {
    mocks.loadCategoryList.mockResolvedValue({ ...CATEGORIES, truncated: true });
    const markup = await listPage({ category: 'zz' });
    expect(markup).toContain('Category not listed (zz)');
  });

  it('trims again after cutting the search text', async () => {
    await listPage({ q: `${'a'.repeat(99)}  b` });
    expect(mocks.fetchProducts.mock.calls[0][1].search).toBe('a'.repeat(99));
  });

  it('falls back to a hidden category field when the categories cannot be loaded', async () => {
    mocks.loadCategoryList.mockResolvedValue(null);
    const markup = await listPage({ category: 'c2' });
    expect(markup).toContain('type="hidden" name="category" value="c2"');
    expect(markup).not.toContain('All categories');
  });

  it('passes the category list to the new and edit pages', async () => {
    mocks.fetchProducts.mockResolvedValue(list([], 0));
    expect(mocks.loadCategoryList).not.toHaveBeenCalled();
    await NewProductPage();
    expect(mocks.loadCategoryList).toHaveBeenCalledWith('store1');
  });
});
