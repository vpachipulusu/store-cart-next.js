/** KAN-75: slug checks that keep made-up URLs away from the cache and the backend. */
import { describe, expect, it } from 'vitest';
import { isInternalStorefrontPath, isValidCatalogueSlug } from '@/lib/storefront/host';
import { cleanSearch } from '@/lib/storefront/catalogue';

describe('isValidCatalogueSlug', () => {
  it.each(['mug', 'blue-mug-2', 'a'.repeat(200)])('accepts %s', (slug) => {
    expect(isValidCatalogueSlug(slug)).toBe(true);
  });

  it.each(['', 'Mug', 'a--b', '-a', 'a-', 'x.png', 'a b', 'a/b', 'a'.repeat(201)])(
    'rejects %j',
    (slug) => {
      expect(isValidCatalogueSlug(slug)).toBe(false);
    }
  );
});

describe('isInternalStorefrontPath', () => {
  it.each([
    '/storefront',
    '/storefront/acme',
    '/storefront-preview/acme',
    '//storefront/acme',
    '/STOREFRONT/acme',
    '/%73torefront/acme',
  ])('matches %s', (path) => {
    expect(isInternalStorefrontPath(path)).toBe(true);
  });

  it.each(['/storefrontx', '/storefront-previewx', '/storefronts/a', '/', '/s/acme', '/%E0%A4%A'])(
    'does not match %s',
    (path) => {
      expect(isInternalStorefrontPath(path)).toBe(false);
    }
  );
});

describe('cleanSearch control characters', () => {
  it('turns control characters into spaces, which the backend would reject', () => {
    expect(cleanSearch('mug\u0000\u0007 \u007fcup')).toBe('mug cup');
  });

  it('cuts by code point, never splitting an emoji', () => {
    const text = `${'a'.repeat(99)}😀😀`;
    expect(Array.from(cleanSearch(text))).toHaveLength(100);
    expect(cleanSearch(text).endsWith('😀')).toBe(true);
  });
});
