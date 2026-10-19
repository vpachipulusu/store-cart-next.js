/** KAN-75: storefront page logic that unit tests can reach: the category page clamp and an empty store's home page. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  getPublicStore: vi.fn(),
  getProductPage: vi.fn(),
  getCategories: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));

vi.mock('server-only', () => ({}));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/lib/api/storefront-catalogue', () => ({
  getPublicStore: mocks.getPublicStore,
  getProductPage: mocks.getProductPage,
  getCategories: mocks.getCategories,
}));

import { readPage } from '@/components/storefront/category-listing';
import StoreHomePage from '@/app/storefront/[slug]/page';
import type { ProductPage } from '@/lib/storefront/catalogue';

function page(total: number, number = 1): ProductPage {
  return {
    items: [],
    currency: 'GBP',
    total,
    page: number,
    pageCount: Math.max(1, Math.ceil(total / 24)),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('category paging', () => {
  it('never reads a page past the end: the first page total decides', async () => {
    mocks.getProductPage.mockResolvedValue(page(30));

    await expect(readPage('acme', 'mugs', 9)).resolves.toBeNull();

    expect(mocks.getProductPage).toHaveBeenCalledTimes(1);
    expect(mocks.getProductPage).toHaveBeenCalledWith('acme', 'mugs', 1);
  });

  it('reads a page that exists', async () => {
    mocks.getProductPage.mockResolvedValueOnce(page(30)).mockResolvedValueOnce(page(30, 2));

    const second = await readPage('acme', 'mugs', 2);

    expect(second?.page).toBe(2);
    expect(mocks.getProductPage).toHaveBeenLastCalledWith('acme', 'mugs', 2);
  });

  it('is null for an unknown category and reuses page 1 for page 1', async () => {
    mocks.getProductPage.mockResolvedValueOnce(null).mockResolvedValueOnce(page(3));

    await expect(readPage('acme', 'nope', 2)).resolves.toBeNull();
    await expect(readPage('acme', 'mugs', 1)).resolves.toMatchObject({ total: 3 });
    expect(mocks.getProductPage).toHaveBeenCalledTimes(2);
  });
});

describe('store home page', () => {
  const params = Promise.resolve({ slug: 'acme' });

  it('shows the empty state for a store with no published products', async () => {
    mocks.getPublicStore.mockResolvedValue({ name: 'Acme Goods', slug: 'acme' });
    mocks.getProductPage.mockResolvedValue(page(0));
    mocks.getCategories.mockResolvedValue([]);

    render(await StoreHomePage({ params }));

    expect(screen.getByRole('heading', { level: 1, name: 'Acme Goods' })).toBeInTheDocument();
    expect(screen.getByText('New products are coming soon.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Shop by category' })).not.toBeInTheDocument();
  });

  it('reads nothing else for an unknown store', async () => {
    mocks.getPublicStore.mockResolvedValue(null);

    await expect(StoreHomePage({ params })).rejects.toThrow('NEXT_NOT_FOUND');

    expect(mocks.getProductPage).not.toHaveBeenCalled();
    expect(mocks.getCategories).not.toHaveBeenCalled();
  });
});
