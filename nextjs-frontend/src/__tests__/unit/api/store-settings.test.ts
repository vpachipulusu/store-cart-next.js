// @vitest-environment node
/** KAN-82, KAN-83: the store settings wrapper calls the generated SDK, checks the body shape, and curates errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  callBackend: vi.fn(),
  getStoreSettings: vi.fn(),
  updateStoreSettings: vi.fn(),
}));
vi.mock('server-only', () => ({}));
vi.mock('@/lib/api/server', () => ({
  callBackend: mocks.callBackend,
  BACKEND_ERROR_MESSAGE: 'Request failed',
}));
vi.mock('@/lib/api/generated', () => ({
  getStoreSettings: mocks.getStoreSettings,
  updateStoreSettings: mocks.updateStoreSettings,
}));

import {
  fetchStoreSettings,
  saveStoreSettings,
  STORE_SETTINGS_FAILED_MESSAGE,
  STORE_SETTINGS_FORBIDDEN_MESSAGE,
  STORE_SETTINGS_RATE_LIMITED_MESSAGE,
  STORE_SETTINGS_SESSION_MESSAGE,
  STORE_SETTINGS_UNAVAILABLE_MESSAGE,
  storeSettingsErrorMessage,
} from '@/lib/api/store-settings';

const BODY = {
  shipping_flat_rate_minor: 499,
  free_shipping_threshold_minor: null,
  tax_rate_bps: 2000,
  prices_include_tax: false,
  updated_at: '2026-10-19T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.callBackend.mockImplementation(async (call: (client: unknown) => Promise<unknown>) => {
    await call('client');
    return { success: true, data: BODY };
  });
});

describe('fetchStoreSettings', () => {
  it('reads the settings of the given store', async () => {
    const result = await fetchStoreSettings('store1');

    expect(result).toEqual({ success: true, data: BODY });
    expect(mocks.getStoreSettings).toHaveBeenCalledWith({
      client: 'client',
      path: { store_id: 'store1' },
    });
  });

  it('refuses a body that is not the settings shape', async () => {
    mocks.callBackend.mockResolvedValue({ success: true, data: [] });

    expect(await fetchStoreSettings('store1')).toMatchObject({ success: false, status: 502 });
  });

  it('passes a backend failure through', async () => {
    const failure = { success: false, error: 'Forbidden', status: 403 };
    mocks.callBackend.mockResolvedValue(failure);

    expect(await fetchStoreSettings('store1')).toBe(failure);
  });
});

describe('saveStoreSettings', () => {
  it('patches the given store with the body', async () => {
    const body = { tax_rate_bps: 2000 };

    const result = await saveStoreSettings('store1', body);

    expect(result.success).toBe(true);
    expect(mocks.updateStoreSettings).toHaveBeenCalledWith({
      client: 'client',
      path: { store_id: 'store1' },
      body,
    });
  });
});

describe('storeSettingsErrorMessage', () => {
  it.each([
    [{ error: 'x' }, STORE_SETTINGS_UNAVAILABLE_MESSAGE],
    [{ error: 'x', status: 401 }, STORE_SETTINGS_SESSION_MESSAGE],
    [{ error: 'x', status: 403 }, STORE_SETTINGS_FORBIDDEN_MESSAGE],
    [{ error: 'x', status: 429 }, STORE_SETTINGS_RATE_LIMITED_MESSAGE],
    [{ error: 'x', status: 503 }, STORE_SETTINGS_UNAVAILABLE_MESSAGE],
    [{ error: 'x', status: 500 }, STORE_SETTINGS_FAILED_MESSAGE],
    [{ error: 'Request failed', status: 422 }, STORE_SETTINGS_FAILED_MESSAGE],
    [{ error: '', status: 404 }, STORE_SETTINGS_FAILED_MESSAGE],
  ])('%j -> fixed message', (result, expected) => {
    expect(storeSettingsErrorMessage(result)).toBe(expected);
  });

  it('shows a curated 404 or 422 text', () => {
    expect(storeSettingsErrorMessage({ error: 'Store not found', status: 404 })).toBe(
      'Store not found'
    );
  });

  it('does not show a very long backend text', () => {
    expect(storeSettingsErrorMessage({ error: 'x'.repeat(201), status: 422 })).toBe(
      STORE_SETTINGS_FAILED_MESSAGE
    );
  });
});
