// @vitest-environment node
/**
 * KAN-255: the orders and store settings pages show the setup state for a store with no database yet
 * (PROVISIONING or FAILED) and never call the store-scoped API for it. The product pages are covered in
 * products-pages.test.tsx.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  fetchOrders: vi.fn(),
  fetchOrder: vi.fn(),
  fetchStoreSettings: vi.fn(),
  fetchPlatformCurrency: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  notFound: vi.fn(),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { error: vi.fn() } }));
vi.mock('@/lib/api/orders', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/orders')>('@/lib/api/orders');
  return { ...actual, fetchOrders: mocks.fetchOrders, fetchOrder: mocks.fetchOrder };
});
vi.mock('@/lib/api/store-settings', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/store-settings')>(
    '@/lib/api/store-settings'
  );
  return { ...actual, fetchStoreSettings: mocks.fetchStoreSettings };
});
vi.mock('@/lib/api/settings', () => ({ fetchPlatformCurrency: mocks.fetchPlatformCurrency }));

import OrdersPage from '@/app/dashboard/orders/page';
import OrderPage from '@/app/dashboard/orders/[orderId]/page';
import StoreSettingsPage from '@/app/dashboard/settings/store/page';

const html = (node: unknown) => renderToStaticMarkup(node as React.ReactElement);

const renderPages = async () => [
  html(await OrdersPage({ searchParams: Promise.resolve({}) })),
  html(await OrderPage({ params: Promise.resolve({ orderId: 'order1' }) })),
  html(await StoreSettingsPage()),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('store-scoped pages for a store that is still being set up (KAN-255)', () => {
  it.each(['PROVISIONING', 'FAILED'])(
    'show the setup state for a %s store without calling the store API',
    async (status) => {
      mocks.getCurrentStoreSelection.mockResolvedValue({
        available: true,
        stores: [],
        selected: { id: 'store1', name: 'Acme Shop', status },
      });

      for (const markup of await renderPages()) {
        expect(markup).toContain('Retry setup');
        expect(markup).toContain('href="/dashboard/onboarding/status/store1"');
        expect(markup).not.toContain('could not be reached');
      }
      expect(mocks.fetchOrders).not.toHaveBeenCalled();
      expect(mocks.fetchOrder).not.toHaveBeenCalled();
      expect(mocks.fetchStoreSettings).not.toHaveBeenCalled();
      expect(mocks.fetchPlatformCurrency).not.toHaveBeenCalled();
    }
  );

  it('render nothing when no store is selected', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });

    for (const markup of await renderPages()) {
      expect(markup).toBe('');
    }
    expect(mocks.fetchOrders).not.toHaveBeenCalled();
  });
});
