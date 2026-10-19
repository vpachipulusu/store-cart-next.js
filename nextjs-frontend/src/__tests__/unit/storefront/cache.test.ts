/** KAN-75: per-store cache tags and keys. */
import { describe, expect, it } from 'vitest';
import {
  STOREFRONT_REVALIDATE_SECONDS,
  storefrontCacheKey,
  storefrontTag,
} from '@/lib/storefront/cache';

describe('storefront cache', () => {
  it('tags every read with its own store', () => {
    expect(storefrontTag('acme')).toBe('storefront:acme');
    expect(storefrontTag('acme')).not.toBe(storefrontTag('acme-two'));
  });

  it('keys a read by name, store and arguments, with empty for null', () => {
    expect(storefrontCacheKey('products', 'acme', null, 2)).toEqual([
      'storefront',
      'products',
      'acme',
      '',
      '2',
    ]);
    expect(storefrontCacheKey('products', 'acme', 'mugs', 1)).not.toEqual(
      storefrontCacheKey('products', 'other', 'mugs', 1)
    );
  });

  it('expires on its own within minutes, so a suspension shows quickly', () => {
    expect(STOREFRONT_REVALIDATE_SECONDS).toBeGreaterThan(0);
    expect(STOREFRONT_REVALIDATE_SECONDS).toBeLessThanOrEqual(600);
  });

  it('keeps a numeric zero distinct from a missing argument', () => {
    expect(storefrontCacheKey('products', 'acme', 0)).toEqual(['storefront', 'products', 'acme', '0']);
    expect(storefrontCacheKey('products', 'acme', undefined)).toEqual(
      storefrontCacheKey('products', 'acme', null)
    );
  });
});
