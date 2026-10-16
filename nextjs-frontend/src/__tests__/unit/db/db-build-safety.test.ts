// @vitest-environment node
/**
 * Regression tests for KAN-140: `next build` prerenders every route it considers static. Root-layout reads must
 * return their defaults without any backend, and per-user segments must render on demand.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

beforeEach(() => {
  vi.resetModules();
});

describe('KAN-140: root layout settings reads need no backend (KAN-184)', () => {
  it('returns the default theme', async () => {
    const { getActiveTheme } = await import('@/app/actions/theme-actions');
    const { DEFAULT_THEME } = await import('@/config/themes');

    await expect(getActiveTheme()).resolves.toBe(DEFAULT_THEME);
  });

  it('returns the default font', async () => {
    const { getActiveFont } = await import('@/app/actions/font-actions');
    const { DEFAULT_FONT } = await import('@/config/fonts');

    await expect(getActiveFont()).resolves.toBe(DEFAULT_FONT);
  });
});

describe('KAN-140: per-user segments render on demand', () => {
  beforeEach(() => {
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
