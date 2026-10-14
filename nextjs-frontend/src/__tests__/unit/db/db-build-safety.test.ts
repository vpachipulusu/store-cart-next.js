// @vitest-environment node
/**
 * Regression tests for KAN-140: `next build` prerenders every route it considers static. With no DATABASE_URL
 * (CI, or an image built without secrets) no route may query Prisma during that prerender, and importing the
 * Prisma client must not throw.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('next/cache', () => ({
  revalidatePath: vi.fn(),
  revalidateTag: vi.fn(),
  unstable_cache: (fn: unknown) => fn,
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
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

const findUnique = vi.fn();

let savedDatabaseUrl: string | undefined;

beforeEach(() => {
  savedDatabaseUrl = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  findUnique.mockReset();
  vi.resetModules();
});

afterEach(() => {
  if (savedDatabaseUrl === undefined) delete process.env.DATABASE_URL;
  else process.env.DATABASE_URL = savedDatabaseUrl;
  vi.doUnmock('@/lib/db/client');
});

describe('KAN-140: Prisma client import is build-safe', () => {
  it('imports and constructs the real Prisma client without DATABASE_URL', async () => {
    const { db } = await import('@/lib/db/client');
    expect(db).toBeDefined();
    expect(typeof db.appSettings.findUnique).toBe('function');
  });

  it('reports whether a database is configured', async () => {
    const { isDatabaseConfigured } = await import('@/lib/db/config');
    expect(isDatabaseConfigured()).toBe(false);

    process.env.DATABASE_URL = '   ';
    expect(isDatabaseConfigured()).toBe(false);

    process.env.DATABASE_URL = 'postgresql://user@localhost:5432/db';
    expect(isDatabaseConfigured()).toBe(true);
  });
});

describe('KAN-140: root layout settings reads skip the database when none is configured', () => {
  beforeEach(() => {
    vi.doMock('@/lib/db/client', () => ({ db: { appSettings: { findUnique } } }));
  });

  it('returns the default theme without querying Prisma', async () => {
    const { getActiveTheme } = await import('@/app/actions/theme-actions');
    const { DEFAULT_THEME } = await import('@/config/themes');

    await expect(getActiveTheme()).resolves.toBe(DEFAULT_THEME);
    expect(findUnique).not.toHaveBeenCalled();
  });

  it('returns the default font without querying Prisma', async () => {
    const { getActiveFont } = await import('@/app/actions/font-actions');
    const { DEFAULT_FONT } = await import('@/config/fonts');

    await expect(getActiveFont()).resolves.toBe(DEFAULT_FONT);
    expect(findUnique).not.toHaveBeenCalled();
  });

  it('reads the stored theme and font when a database is configured', async () => {
    process.env.DATABASE_URL = 'postgresql://user@localhost:5432/db';
    findUnique.mockImplementation(({ where }: { where: { key: string } }) =>
      Promise.resolve({ value: where.key === 'active_theme' ? 'ocean' : 'roboto' })
    );
    const { getActiveTheme } = await import('@/app/actions/theme-actions');
    const { getActiveFont } = await import('@/app/actions/font-actions');

    await expect(getActiveTheme()).resolves.toBe('ocean');
    await expect(getActiveFont()).resolves.toBe('roboto');
    expect(findUnique).toHaveBeenCalledTimes(2);
  });
});

describe('KAN-140: DB-backed, per-user segments render on demand', () => {
  beforeEach(() => {
    vi.doMock('@/lib/db/client', () => ({ db: {} }));
    vi.doMock('@/lib/firebase/client', () => ({ auth: {} }));
  });

  it.each([
    ['admin layout (covers every /admin route)', '@/app/(admin)/admin/layout'],
    ['dashboard layout (covers every /dashboard route)', '@/app/dashboard/layout'],
    ['pricing page', '@/app/pricing/page'],
  ])('%s is force-dynamic', async (_name, modulePath) => {
    const segment = await import(modulePath);
    expect(segment.dynamic).toBe('force-dynamic');
  });
});
