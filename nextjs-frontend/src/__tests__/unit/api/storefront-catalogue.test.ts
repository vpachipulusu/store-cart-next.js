// @vitest-environment node
/**
 * KAN-75: the storefront catalogue wrapper maps backend bodies to public shapes, caches shared reads per store
 * with the store's tag, never caches failures, and keeps search uncached with the visitor's IP.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

interface CacheCall {
  keyParts: string[];
  options: { tags: string[]; revalidate: number };
}

const mocks = vi.hoisted(() => ({
  callBackend: vi.fn(),
  cacheCalls: [] as CacheCall[],
}));

vi.mock('server-only', () => ({}));
vi.mock('next/cache', () => ({
  unstable_cache:
    (load: () => Promise<unknown>, keyParts: string[], options: CacheCall['options']) => () => {
      mocks.cacheCalls.push({ keyParts, options });
      return load();
    },
}));
vi.mock('@/lib/api/server', () => ({ callBackend: mocks.callBackend }));

import {
  getCategories,
  getProduct,
  getProductPage,
  getPublicStore,
  mapProduct,
  mapProductPage,
  searchProducts,
  STOREFRONT_UNAVAILABLE_MESSAGE,
} from '@/lib/api/storefront-catalogue';

const listBody = {
  data: [
    {
      title: 'Mug',
      slug: 'mug',
      min_price_minor: 1000,
      max_price_minor: 1200,
      image: { url: 'https://img.example/m.jpg', alt_text: null },
    },
  ],
  currency: 'GBP',
  total: 30,
  limit: 24,
  offset: 24,
};

const productBody = {
  title: 'Mug',
  slug: 'mug',
  description: 'Big',
  currency: 'GBP',
  options: [{ name: 'Colour', values: [{ id: 'v-red', value: 'Red' }] }],
  variants: [
    {
      id: 'var1',
      price_minor: 1000,
      compare_at_price_minor: null,
      in_stock: true,
      option_value_ids: ['v-red'],
    },
  ],
  images: [
    { url: 'https://img.example/1.jpg', alt_text: '  ' },
    { url: 'https://img.example/2.jpg', alt_text: 'Side view' },
  ],
  categories: [{ name: 'Kitchen', slug: 'kitchen', parent_slug: null }],
};

function backendReturns(result: unknown): void {
  mocks.callBackend.mockResolvedValue(result);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.cacheCalls.length = 0;
});

describe('mapping', () => {
  it('maps a listing page and fills a missing alt with the title', () => {
    expect(mapProductPage(listBody, 2)).toEqual({
      items: [
        {
          title: 'Mug',
          slug: 'mug',
          minPriceMinor: 1000,
          maxPriceMinor: 1200,
          image: { url: 'https://img.example/m.jpg', alt: 'Mug' },
        },
      ],
      currency: 'GBP',
      total: 30,
      page: 2,
      pageCount: 2,
    });
  });

  it('maps a product and fills a blank alt from the title', () => {
    const product = mapProduct(productBody);

    expect(product.images).toEqual([
      { url: 'https://img.example/1.jpg', alt: 'Mug' },
      { url: 'https://img.example/2.jpg', alt: 'Side view' },
    ]);
    expect(product.variants[0]).toEqual({
      id: 'var1',
      priceMinor: 1000,
      compareAtPriceMinor: null,
      inStock: true,
      optionValueIds: ['v-red'],
    });
    expect(product.options).toEqual([{ name: 'Colour', values: [{ id: 'v-red', value: 'Red' }] }]);
    expect(product.categories).toEqual([{ name: 'Kitchen', slug: 'kitchen', parentSlug: null }]);
  });
});

describe('cached reads', () => {
  it('tag the store and key by read and arguments', async () => {
    backendReturns({ success: true, data: { page: listBody } });

    const page = await getProductPage('acme', 'mugs', 2);

    expect(page?.total).toBe(30);
    expect(mocks.cacheCalls).toEqual([
      {
        keyParts: ['storefront', 'products', 'acme', 'mugs', '2'],
        options: { tags: ['storefront:acme'], revalidate: 300 },
      },
    ]);
    expect(mocks.callBackend.mock.calls[0][1]).toEqual({ shared: true });
  });

  it('ask for the page as limit and offset, and box the list body whole', async () => {
    const get = vi.fn().mockResolvedValue({ data: listBody, response: new Response() });
    mocks.callBackend.mockImplementation(async (call: (client: unknown) => Promise<unknown>) => ({
      success: true,
      data: ((await call({ get })) as { data: unknown }).data,
    }));

    const page = await getProductPage('acme', null, 3);

    expect(get.mock.calls[0][0]).toMatchObject({
      url: '/v1/storefront/{slug}/products',
      path: { slug: 'acme' },
      query: { category: undefined, q: undefined, limit: 24, offset: 48 },
    });
    expect(page).toMatchObject({ currency: 'GBP', total: 30, page: 3 });
  });

  it('read a 404 as null', async () => {
    backendReturns({ success: false, error: 'Product not found', status: 404 });

    await expect(getProduct('acme', 'nope')).resolves.toBeNull();
  });

  it('throw on any other failure so it is never cached', async () => {
    backendReturns({ success: false, error: 'Backend unavailable' });

    await expect(getCategories('acme')).rejects.toThrow(STOREFRONT_UNAVAILABLE_MESSAGE);
  });

  it('never call the backend for a slug that cannot be a store', async () => {
    await expect(getPublicStore('www')).resolves.toBeNull();
    await expect(getProduct('Bad Slug', 'mug')).resolves.toBeNull();

    expect(mocks.callBackend).not.toHaveBeenCalled();
    expect(mocks.cacheCalls).toEqual([]);
  });

  it('keep only the public store fields', async () => {
    backendReturns({ success: true, data: { name: 'Acme', slug: 'acme', extra: 'x' } });

    await expect(getPublicStore('acme')).resolves.toEqual({ name: 'Acme', slug: 'acme' });
  });

  it('map categories and a product', async () => {
    backendReturns({ success: true, data: productBody.categories });
    await expect(getCategories('acme')).resolves.toEqual([
      { name: 'Kitchen', slug: 'kitchen', parentSlug: null },
    ]);

    backendReturns({ success: true, data: productBody });
    await expect(getProduct('acme', 'mug')).resolves.toMatchObject({
      title: 'Mug',
      currency: 'GBP',
    });
  });
});

describe('search', () => {
  it('is not cached and forwards the visitor (no shared option)', async () => {
    backendReturns({ success: true, data: { page: { ...listBody, total: 1 } } });

    const results = await searchProducts('acme', 'mug', 1);

    expect(results?.total).toBe(1);
    expect(mocks.cacheCalls).toEqual([]);
    expect(mocks.callBackend.mock.calls[0][1]).toEqual({ withSession: false });
  });

  it('is null for a slug that cannot be a store', async () => {
    await expect(searchProducts('www', 'mug', 1)).resolves.toBeNull();
  });
});
