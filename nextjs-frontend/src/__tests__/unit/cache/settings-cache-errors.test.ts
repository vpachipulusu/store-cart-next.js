// @vitest-environment node
/**
 * KAN-142: theme, font and currency reads are wrapped in `unstable_cache` for 1 hour. A database error
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
  it('caches theme for 1h under the active-theme tag', async () => {
    await import('@/app/actions/theme-actions');
    expect(mocks.registry['active-theme']).toEqual({ revalidate: 3600, tags: ['active-theme'] });
  });

  it('caches font for 1h under the active-font tag', async () => {
    await import('@/app/actions/font-actions');
    expect(mocks.registry['active-font']).toEqual({ revalidate: 3600, tags: ['active-font'] });
  });

  it('caches currency for 1h under the currency-setting tag', async () => {
    await import('@/config/subscriptions');
    expect(mocks.registry['currency-symbol']).toEqual({
      revalidate: 3600,
      tags: ['currency-setting'],
    });
  });
});

describe('KAN-142: a database error is logged and not cached', () => {
  it('theme: falls back to the default, logs, and recovers on the next call', async () => {
    mocks.findUnique.mockRejectedValueOnce(DB_ERROR).mockResolvedValueOnce({ value: 'ocean' });
    const { getActiveTheme } = await import('@/app/actions/theme-actions');
    const { DEFAULT_THEME } = await import('@/config/themes');

    await expect(getActiveTheme()).resolves.toBe(DEFAULT_THEME);
    expect(mocks.logError).toHaveBeenCalledTimes(1);
    await expect(getActiveTheme()).resolves.toBe('ocean');
  });

  it('font: falls back to the default, logs, and recovers on the next call', async () => {
    mocks.findUnique.mockRejectedValueOnce(DB_ERROR).mockResolvedValueOnce({ value: 'roboto' });
    const { getActiveFont } = await import('@/app/actions/font-actions');
    const { DEFAULT_FONT } = await import('@/config/fonts');

    await expect(getActiveFont()).resolves.toBe(DEFAULT_FONT);
    expect(mocks.logError).toHaveBeenCalledTimes(1);
    await expect(getActiveFont()).resolves.toBe('roboto');
  });

  it('currency: falls back to $, logs, and recovers on the next call', async () => {
    mocks.findUnique.mockRejectedValueOnce(DB_ERROR).mockResolvedValueOnce({ value: 'EUR' });
    const { getCurrencySymbol } = await import('@/config/subscriptions');
    const { CURRENCIES } = await import('@/config/currencies');
    const euro = CURRENCIES.find((c) => c.code === 'EUR')!.symbol;

    await expect(getCurrencySymbol()).resolves.toBe('$');
    expect(mocks.logError).toHaveBeenCalledTimes(1);
    await expect(getCurrencySymbol()).resolves.toBe(euro);
  });

  it('still caches successful reads', async () => {
    mocks.findUnique.mockResolvedValue({ value: 'ocean' });
    const { getActiveTheme } = await import('@/app/actions/theme-actions');

    await getActiveTheme();
    await getActiveTheme();
    expect(mocks.findUnique).toHaveBeenCalledTimes(1);
  });
});

describe('KAN-142: admin saves use read-your-writes updateTag', () => {
  async function save(key: string) {
    vi.doMock('next/headers', () => ({
      cookies: async () => ({ get: () => ({ value: 'session-cookie' }) }),
    }));
    vi.doMock('@/lib/auth/verified-session', () => ({
      verifyVerifiedSessionCookie: async () => ({ uid: 'fb-admin' }),
    }));
    vi.doMock('@/lib/db/client', () => ({
      db: {
        user: {
          findUnique: async () => ({ id: 'u1', adminUser: { permissions: ['*'] } }),
        },
        appSettings: { upsert: async () => ({ id: 's1' }) },
        auditLog: { create: async () => ({}) },
      },
    }));
    const { upsertAppSettingAction } = await import('@/app/actions/admin/settings-actions');
    return upsertAppSettingAction({ key, value: 'x', category: 'general' });
  }

  beforeEach(() => {
    mocks.updateTag.mockReset();
    mocks.revalidateTag.mockReset();
  });

  it.each([
    ['active_theme', 'active-theme'],
    ['app_font', 'active-font'],
    ['currency', 'currency-setting'],
  ])('saving %s updates the %s tag', async (key, tag) => {
    const result = await save(key);

    expect(result.success).toBe(true);
    expect(mocks.updateTag).toHaveBeenCalledTimes(1);
    expect(mocks.updateTag).toHaveBeenCalledWith(tag);
    expect(mocks.revalidateTag).not.toHaveBeenCalled();
  });

  it('does not touch any tag for unrelated settings', async () => {
    await save('site_name');

    expect(mocks.updateTag).not.toHaveBeenCalled();
  });
});
