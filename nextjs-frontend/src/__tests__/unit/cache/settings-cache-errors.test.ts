// @vitest-environment node
/**
 * KAN-142: the currency read is wrapped in `unstable_cache` for 1 hour. A database error
 * must be logged and must NOT be cached (otherwise the default is served for the whole hour), and the
 * cache options (revalidate + tags) must stay wired to the tags the admin save path invalidates.
 *
 * The `unstable_cache` mock below records its options and memoizes only successful results, like the
 * real one: a thrown error is never stored. It is deliberately not the identity function.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const registry: Record<string, { revalidate?: number; tags?: string[] }> = {};
  return {
    registry,
    findUnique: vi.fn(),
    logError: vi.fn(),
    updateTag: vi.fn(),
    revalidateTag: vi.fn(),
  };
});

vi.mock('next/cache', () => ({
  revalidatePath: vi.fn(),
  revalidateTag: mocks.revalidateTag,
  updateTag: mocks.updateTag,
  unstable_cache: (
    fn: (...args: unknown[]) => Promise<unknown>,
    keyParts: string[],
    options: { revalidate?: number; tags?: string[] }
  ) => {
    mocks.registry[keyParts[0]] = options;
    let hit = false;
    let value: unknown;
    return async (...args: unknown[]) => {
      if (hit) return value;
      value = await fn(...args); // a rejection propagates and nothing is stored
      hit = true;
      return value;
    };
  },
}));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));
vi.mock('@/lib/db/client', () => ({ db: { appSettings: { findUnique: mocks.findUnique } } }));
vi.mock('stripe', () => ({ default: class {} }));
vi.mock('next/font/google', () => {
  const font = () => ({ className: 'font', variable: '--font', style: { fontFamily: 'font' } });
  return Object.fromEntries(
    [
      'Inter',
      'Open_Sans',
      'Roboto',
      'Lato',
      'Poppins',
      'Nunito',
      'Work_Sans',
      'Source_Sans_3',
      'Montserrat',
      'Raleway',
      'Fraunces',
    ].map((name) => [name, font])
  );
});

const DB_ERROR = new Error('connection refused');

beforeEach(() => {
  process.env.DATABASE_URL = 'postgresql://user@localhost:5432/db';
  for (const key of Object.keys(mocks.registry)) delete mocks.registry[key];
  mocks.findUnique.mockReset();
  mocks.logError.mockReset();
  vi.resetModules();
});

describe('KAN-142: cache options', () => {
  it('caches currency for 1h under the currency-setting tag', async () => {
    await import('@/config/subscriptions');
    expect(mocks.registry['currency-symbol']).toEqual({
      revalidate: 3600,
      tags: ['currency-setting'],
    });
  });
});

describe('KAN-142: a database error is logged and not cached', () => {
  it('currency: falls back to $, logs, and recovers on the next call', async () => {
    mocks.findUnique.mockRejectedValueOnce(DB_ERROR).mockResolvedValueOnce({ value: 'EUR' });
    const { getCurrencySymbol } = await import('@/config/subscriptions');
    const { CURRENCIES } = await import('@/config/currencies');
    const euro = CURRENCIES.find((c) => c.code === 'EUR')!.symbol;

    await expect(getCurrencySymbol()).resolves.toBe('$');
    expect(mocks.logError).toHaveBeenCalledTimes(1);
    await expect(getCurrencySymbol()).resolves.toBe(euro);
  });
});
