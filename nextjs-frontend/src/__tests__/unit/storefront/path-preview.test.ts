/** KAN-202: the preview-only `/s/{slug}` path helpers. */
import { describe, expect, it } from 'vitest';
import { isStorefrontPathPreviewEnabled, parseStorePath } from '@/lib/storefront/host';

describe('isStorefrontPathPreviewEnabled', () => {
  it.each([
    [{ STOREFRONT_PATH_PREVIEW: 'true', VERCEL_ENV: 'preview' }, true],
    [{ STOREFRONT_PATH_PREVIEW: 'true', VERCEL_ENV: 'development' }, true],
    [{ STOREFRONT_PATH_PREVIEW: 'true' }, true],
    [{ STOREFRONT_PATH_PREVIEW: 'true', VERCEL_ENV: 'production' }, false],
    [{ STOREFRONT_PATH_PREVIEW: 'false', VERCEL_ENV: 'preview' }, false],
    [{ STOREFRONT_PATH_PREVIEW: 'TRUE', VERCEL_ENV: 'preview' }, false],
    [{ STOREFRONT_PATH_PREVIEW: '1', VERCEL_ENV: 'preview' }, false],
    [{ STOREFRONT_PATH_PREVIEW: '', VERCEL_ENV: 'preview' }, false],
    [{ VERCEL_ENV: 'preview' }, false],
    [{}, false],
  ])('%j -> %s', (env, expected) => {
    expect(isStorefrontPathPreviewEnabled(env)).toBe(expected);
  });
});

describe('parseStorePath', () => {
  it('returns the slug and the remaining path', () => {
    expect(parseStorePath('/s/acme')).toEqual({ slug: 'acme', rest: '' });
    expect(parseStorePath('/s/acme/products')).toEqual({ slug: 'acme', rest: '/products' });
  });

  it.each(['/', '/dashboard', '/storefront/acme', '/shop/acme', '/sx/acme', '/S/acme'])(
    'is not a preview path: %s',
    (pathname) => {
      expect(parseStorePath(pathname)).toBeNull();
    }
  );

  it.each([
    '/s',
    '/s/',
    '/s//acme',
    '/s/ab',
    '/s/Acme',
    '/s/-acme',
    '/s/acme--x',
    '/s/ac_me',
    '/s/acme%2Fx',
    '/s/www',
    '/s/admin',
    '/s/api',
  ])('is a preview path without a valid slug: %s', (pathname) => {
    expect(parseStorePath(pathname)).toEqual({ slug: null, rest: expect.any(String) });
  });
});
