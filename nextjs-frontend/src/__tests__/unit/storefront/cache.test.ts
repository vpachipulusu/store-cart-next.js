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

  it('expires on its own within minutes', () => {
    expect(STOREFRONT_REVALIDATE_SECONDS).toBe(300);
  });
});
