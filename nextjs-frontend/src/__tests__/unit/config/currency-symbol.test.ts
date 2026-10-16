// @vitest-environment node
/** KAN-50: getCurrencySymbol reads the backend currency and falls back to '$' on any failure. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ fetchPlatformCurrency: vi.fn(), logError: vi.fn() }));

vi.mock('next/cache', () => ({ unstable_cache: (fn: unknown) => fn }));
vi.mock('@/lib/api/settings', () => ({ fetchPlatformCurrency: mocks.fetchPlatformCurrency }));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));
vi.mock('stripe', () => ({ default: class {} }));

import { getCurrencySymbol } from '@/config/subscriptions';
import { CURRENCIES } from '@/config/currencies';

describe('getCurrencySymbol', () => {
  beforeEach(() => {
    mocks.fetchPlatformCurrency.mockReset();
    mocks.logError.mockReset();
  });

  it('maps the backend currency code to its symbol', async () => {
    mocks.fetchPlatformCurrency.mockResolvedValue('EUR');
    await expect(getCurrencySymbol()).resolves.toBe(
      CURRENCIES.find((c) => c.code === 'EUR')!.symbol
    );
  });

  it('falls back to $ for an unknown code', async () => {
    mocks.fetchPlatformCurrency.mockResolvedValue('ZZZ');
    await expect(getCurrencySymbol()).resolves.toBe('$');
  });

  it('logs and falls back to $ on a backend error, then recovers', async () => {
    mocks.fetchPlatformCurrency
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce('EUR');
    await expect(getCurrencySymbol()).resolves.toBe('$');
    expect(mocks.logError).toHaveBeenCalledTimes(1);
    await expect(getCurrencySymbol()).resolves.not.toBe('$');
  });
});
