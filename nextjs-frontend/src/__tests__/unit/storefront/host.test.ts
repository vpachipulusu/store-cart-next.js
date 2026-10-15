import { describe, expect, it } from 'vitest';
import { parseStoreSlug, resolvePlatformRootDomain } from '@/lib/storefront/host';

const ROOT = 'storecart.test';

describe('parseStoreSlug', () => {
  it.each([
    ['acme.storecart.test', 'acme'],
    ['acme.storecart.test:3000', 'acme'],
    ['ACME.StoreCart.TEST', 'acme'],
    ['acme.storecart.test.', 'acme'],
    ['my-shop-1.storecart.test', 'my-shop-1'],
  ])('maps %s to store %s', (host, slug) => {
    expect(parseStoreSlug(host, ROOT)).toBe(slug);
  });

  it.each([
    ['the root domain', 'storecart.test'],
    ['the root domain with a port', 'storecart.test:3000'],
    ['a missing host', null],
    ['an empty host', ''],
    ['a reserved name (www)', 'www.storecart.test'],
    ['a reserved name (admin)', 'admin.storecart.test'],
    ['a reserved name (app)', 'app.storecart.test'],
    ['a reserved name (api)', 'api.storecart.test'],
    ['nested labels', 'a.acme.storecart.test'],
    ['too-short label', 'ab.storecart.test'],
    ['an over-long label', `${'a'.repeat(64)}.storecart.test`],
    ['a leading hyphen', '-acme.storecart.test'],
    ['a trailing hyphen', 'acme-.storecart.test'],
    ['double hyphens (punycode)', 'xn--acme.storecart.test'],
    ['an underscore', 'ac_me.storecart.test'],
    ['encoded characters', 'ac%2eme.storecart.test'],
    ['an empty label', '.storecart.test'],
    ['userinfo', 'evil@acme.storecart.test'],
    ['a path-like host', 'acme.storecart.test/x'],
    ['whitespace', 'acme .storecart.test'],
    ['a non-ASCII look-alike', 'acmé.storecart.test'],
    ['a suffix look-alike', 'acme.evilstorecart.test'],
    ['a different domain', 'acme.example.com'],
    ['an IPv4 host', '127.0.0.1:3000'],
    ['an IPv6 host', '[::1]:3000'],
    ['a bad port', 'acme.storecart.test:abc'],
    ['an over-long port', 'acme.storecart.test:123456'],
    ['multiple hosts', 'acme.storecart.test,evil.com'],
  ])('rejects %s', (_label, host) => {
    expect(parseStoreSlug(host, ROOT)).toBeNull();
  });

  it('works on *.localhost', () => {
    expect(parseStoreSlug('acme.localhost:3000', 'localhost')).toBe('acme');
    expect(parseStoreSlug('localhost:3000', 'localhost')).toBeNull();
  });
});

describe('resolvePlatformRootDomain', () => {
  it('defaults to localhost', () => {
    expect(resolvePlatformRootDomain(undefined)).toBe('localhost');
    expect(resolvePlatformRootDomain('  ')).toBe('localhost');
  });

  it('normalises case, port and trailing dot', () => {
    expect(resolvePlatformRootDomain('StoreCart.Com.')).toBe('storecart.com');
    expect(resolvePlatformRootDomain('storecart.com:443')).toBe('storecart.com');
  });

  it('falls back to localhost for an invalid value', () => {
    expect(resolvePlatformRootDomain('https://storecart.com/x')).toBe('localhost');
  });
});
