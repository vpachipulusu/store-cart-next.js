// @vitest-environment node
/** KAN-82, KAN-83: the settings action validates input, takes the store from the server, and curates errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  saveStoreSettings: vi.fn(),
}));

vi.mock('server-only', () => ({}));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api/store-settings', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/store-settings')>(
    '@/lib/api/store-settings'
  );
  return { ...actual, saveStoreSettings: mocks.saveStoreSettings };
});

import { updateStoreSettingsAction } from '@/app/actions/store-settings-actions';
import {
  STORE_SETTINGS_FORBIDDEN_MESSAGE,
  STORE_SETTINGS_UNAVAILABLE_MESSAGE,
} from '@/lib/api/store-settings';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

const INPUT = {
  shippingFlatRateMinor: 499,
  freeShippingThresholdMinor: 5000,
  taxRateBps: 2000,
  pricesIncludeTax: true,
};
const SAVED = {
  shipping_flat_rate_minor: 499,
  free_shipping_threshold_minor: 5000,
  tax_rate_bps: 2000,
  prices_include_tax: true,
  updated_at: '2026-10-19T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getCurrentStoreSelection.mockResolvedValue({ available: true, selected: { id: 'store1' } });
});

describe('updateStoreSettingsAction', () => {
  it('sends minor units and basis points for the server-selected store', async () => {
    mocks.saveStoreSettings.mockResolvedValue({ success: true, data: SAVED });

    const result = await updateStoreSettingsAction(INPUT);

    expect(result).toEqual({ success: true, data: SAVED });
    expect(mocks.saveStoreSettings).toHaveBeenCalledWith('store1', {
      shipping_flat_rate_minor: 499,
      free_shipping_threshold_minor: 5000,
      tax_rate_bps: 2000,
      prices_include_tax: true,
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/settings/store');
  });

  it('sends a null threshold to remove it', async () => {
    mocks.saveStoreSettings.mockResolvedValue({ success: true, data: SAVED });

    await updateStoreSettingsAction({ ...INPUT, freeShippingThresholdMinor: null });

    expect(mocks.saveStoreSettings.mock.calls[0]?.[1]).toMatchObject({
      free_shipping_threshold_minor: null,
    });
  });

  it('rejects invalid input before any lookup or call', async () => {
    const result = await updateStoreSettingsAction({ ...INPUT, taxRateBps: 10001 });

    expect(result.success).toBe(false);
    expect(mocks.getCurrentStoreSelection).not.toHaveBeenCalled();
    expect(mocks.saveStoreSettings).not.toHaveBeenCalled();
  });

  it('fails when the store list is unavailable', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({ available: false, error: 'x' });

    expect(await updateStoreSettingsAction(INPUT)).toEqual({
      success: false,
      error: STORES_UNAVAILABLE_MESSAGE,
    });
  });

  it('fails when no store is selected', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({ available: true, selected: null });

    const result = await updateStoreSettingsAction(INPUT);

    expect(result.success).toBe(false);
    expect(mocks.saveStoreSettings).not.toHaveBeenCalled();
  });

  it('shows a fixed message for a forbidden role and hides unknown backend text', async () => {
    mocks.saveStoreSettings.mockResolvedValueOnce({
      success: false,
      error: 'Forbidden',
      status: 403,
    });
    mocks.saveStoreSettings.mockResolvedValueOnce({
      success: false,
      error: 'secret internals',
      status: 500,
    });

    const forbidden = await updateStoreSettingsAction(INPUT);
    const failed = await updateStoreSettingsAction(INPUT);

    expect(forbidden).toEqual({ success: false, error: STORE_SETTINGS_FORBIDDEN_MESSAGE });
    expect(JSON.stringify(failed)).not.toContain('secret internals');
  });

  it('shows the backend 422 text when it is curated', async () => {
    mocks.saveStoreSettings.mockResolvedValue({
      success: false,
      error: 'Tax rate must be a whole number of basis points from 0 to 10000',
      status: 422,
    });

    const result = await updateStoreSettingsAction(INPUT);

    expect(result.error).toContain('Tax rate must be');
  });

  it('reports an unreachable backend with the unavailable message', async () => {
    mocks.saveStoreSettings.mockResolvedValue({ success: false, error: 'Backend unavailable' });

    expect(await updateStoreSettingsAction(INPUT)).toEqual({
      success: false,
      error: STORE_SETTINGS_UNAVAILABLE_MESSAGE,
    });
  });
});
