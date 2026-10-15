import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { parseStoreSlug, resolvePlatformRootDomain, RESERVED_SLUGS } from '@/lib/storefront/host';

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

describe('production root-domain warning', () => {
  it('warns once, without throwing, when the root domain is unset in production', async () => {
    vi.resetModules();
    vi.stubEnv('NODE_ENV', 'production');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const fresh = await import('@/lib/storefront/host');

    expect(fresh.resolvePlatformRootDomain(undefined)).toBe('localhost');
    expect(fresh.resolvePlatformRootDomain('https://bad/x')).toBe('localhost');

    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
    vi.unstubAllEnvs();
  });

  it('stays quiet outside production and when configured', async () => {
    vi.resetModules();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const fresh = await import('@/lib/storefront/host');
    fresh.resolvePlatformRootDomain(undefined);
    vi.stubEnv('NODE_ENV', 'production');
    expect(fresh.resolvePlatformRootDomain('storecart.com')).toBe('storecart.com');
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
    vi.unstubAllEnvs();
  });
});

describe('reserved slugs parity with the backend', () => {
  it('matches RESERVED_SLUGS in fastapi_backend/app/core/slugs.py', () => {
    const source = readFileSync(
      path.resolve(__dirname, '../../../../../fastapi_backend/app/core/slugs.py'),
      'utf8'
    );
    const block = source.match(/RESERVED_SLUGS[^=]*=\s*frozenset\(\s*\{([\s\S]*?)\}\s*\)/);
    expect(block).not.toBeNull();
    const backend = [...block![1].matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]).sort();

    expect(backend.length).toBeGreaterThan(50);
    expect([...RESERVED_SLUGS].sort()).toEqual(backend);
  });
});
