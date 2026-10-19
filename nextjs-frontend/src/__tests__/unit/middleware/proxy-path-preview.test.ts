/** KAN-202: preview-only `/s/{slug}` access. Flag x environment matrix, 404 parity and header spoofing. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '@/proxy';
import { STORE_SLUG_HEADER } from '@/lib/storefront/host';

function request(host: string, path: string, headers: Record<string, string> = {}) {
  return new NextRequest(`http://${host}${path}`, { headers: { host, ...headers } });
}

const ROOT_HOST = 'storecart.test';
const CSP = "default-src 'none'; style-src 'unsafe-inline'";
const rewriteTarget = (response: Response) => response.headers.get('x-middleware-rewrite');
const overridden = (response: Response, name: string) =>
  response.headers.get(`x-middleware-request-${name}`);
const rewritePath = (response: Response) => new URL(rewriteTarget(response)!).pathname;

function configure(
  flag: string | undefined,
  vercelEnv: string | undefined,
  nodeEnv: string = 'test'
) {
  vi.stubEnv('PLATFORM_ROOT_DOMAIN', ROOT_HOST);
  vi.stubEnv('STOREFRONT_PATH_PREVIEW', flag);
  vi.stubEnv('VERCEL_ENV', vercelEnv);
  vi.stubEnv('NODE_ENV', nodeEnv);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('/s/{slug} when the preview is enabled', () => {
  beforeEach(() => configure('true', 'preview'));

  it('rewrites to the storefront route and sets the slug marker itself', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme'));

    expect(rewritePath(response)).toBe('/storefront-preview/acme');
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
  });

  it('keeps the query on the store root', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme?x=1'));

    const target = new URL(rewriteTarget(response)!);
    expect(target.pathname).toBe('/storefront-preview/acme');
    expect(target.search).toBe('?x=1');
  });

  it.each(['/s/acme/products', '/s/acme//x', '/s/acme/%2e%2e/x', '/s/ac%6De'])(
    'serves no sub-path or encoded slug: %s',
    async (path) => {
      const response = await proxy(request(ROOT_HOST, path));

      expect(rewritePath(response)).toBe('/storefront-preview/not_found');
      expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
    }
  );

  it('marks the response noindex and keeps the security headers', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme'));

    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(response.headers.get('X-Frame-Options')).toBe('DENY');
    expect(response.headers.get('X-Content-Type-Options')).toBe('nosniff');
  });

  it('overrides a client-supplied slug marker', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme', { [STORE_SLUG_HEADER]: 'victim' }));
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
  });

  it('applies no root-domain auth redirects or API gate', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme/login', { cookie: 'session=abc' }));
    expect(response.headers.get('location')).toBeNull();
    expect(rewritePath(response)).toBe('/storefront-preview/not_found');
  });

  it.each(['/s', '/s/', '/s/ab', '/s/Acme', '/s/acme--x', '/s/www', '/s/admin', '/s/a_b_c'])(
    'rewrites %s to the not-found target with no slug marker',
    async (path) => {
      const response = await proxy(request(ROOT_HOST, path, { [STORE_SLUG_HEADER]: 'acme' }));

      expect(rewritePath(response)).toBe('/storefront-preview/not_found');
      expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
      expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    }
  );

  it('lets a store host win over the /s path', async () => {
    const response = await proxy(request(`acme.${ROOT_HOST}`, '/s/other'));
    expect(rewritePath(response)).toBe('/storefront/acme/s/other');
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
  });
});

describe.each([
  ['flag on, preview, production build', 'true', 'preview', 'production'],
  ['flag on, development, production build', 'true', 'development', 'production'],
  ['flag on, VERCEL_ENV unset, non-production build', 'true', undefined, 'development'],
  ['flag on, VERCEL_ENV unset, test build', 'true', undefined, 'test'],
])('/s/{slug} is served (%s)', (_label, flag, vercelEnv, nodeEnv) => {
  beforeEach(() => configure(flag, vercelEnv, nodeEnv));

  it('rewrites to the storefront route with the slug marker and the locked-down headers', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme'));

    expect(rewritePath(response)).toBe('/storefront-preview/acme');
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(response.headers.get('Content-Security-Policy')).toBe(CSP);
  });
});

describe.each([
  ['flag off, preview', 'false', 'preview', 'production'],
  ['flag unset, preview', undefined, 'preview', 'production'],
  ['flag not exactly true, preview', 'TRUE', 'preview', 'production'],
  ['flag on, production', 'true', 'production', 'production'],
  ['flag on, production, non-production build', 'true', 'production', 'development'],
  ['flag off, production', 'false', 'production', 'production'],
  ['flag unset, production', undefined, 'production', 'production'],
  ['flag on, VERCEL_ENV unset, production build', 'true', undefined, 'production'],
  ['flag on, VERCEL_ENV empty', 'true', '', 'development'],
  ['flag on, VERCEL_ENV unknown', 'true', 'staging', 'development'],
])('/s/{slug} is a 404 target (%s)', (_label, flag, vercelEnv, nodeEnv) => {
  beforeEach(() => configure(flag, vercelEnv, nodeEnv));

  it('rewrites a valid slug to the not-found target without a slug marker', async () => {
    const response = await proxy(request(ROOT_HOST, '/s/acme', { [STORE_SLUG_HEADER]: 'acme' }));

    expect(rewritePath(response)).toBe('/storefront-preview/not_found');
    expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
    expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    expect(response.headers.get('Content-Security-Policy')).toBe(CSP);
  });

  it('leaves host routing working', async () => {
    const response = await proxy(request(`acme.${ROOT_HOST}`, '/'));
    expect(rewritePath(response)).toBe('/storefront/acme');
  });
});

describe('header spoofing on ordinary requests', () => {
  beforeEach(() => configure('true', 'preview'));

  it.each(['/storefront/acme', '/storefront-preview/acme', '/storefront/acme/products/tee'])(
    'sends a direct internal storefront path to the 404 target without the marker: %s',
    async (path) => {
      const response = await proxy(request(ROOT_HOST, path, { [STORE_SLUG_HEADER]: 'acme' }));
      expect(rewritePath(response)).toBe('/storefront-preview/not_found');
      expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
      expect(response.headers.get('X-Robots-Tag')).toBe('noindex');
    }
  );

  it('strips an inbound slug marker on a root-domain request', async () => {
    const response = await proxy(request(ROOT_HOST, '/pricing', { [STORE_SLUG_HEADER]: 'acme' }));
    expect(rewriteTarget(response)).toBeNull();
    expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
    expect(response.headers.get('x-middleware-override-headers') ?? '').not.toContain(
      STORE_SLUG_HEADER
    );
  });

  it('does not touch other routes and adds no noindex header', async () => {
    const response = await proxy(request(ROOT_HOST, '/pricing'));
    expect(rewriteTarget(response)).toBeNull();
    expect(response.headers.get('X-Robots-Tag')).toBeNull();
  });
});
