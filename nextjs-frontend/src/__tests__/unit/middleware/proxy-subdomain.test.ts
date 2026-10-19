/** KAN-64: store subdomains are rewritten to the internal storefront route; everything else is unchanged. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '@/proxy';
import { STORE_SLUG_HEADER } from '@/lib/storefront/host';

function request(
  host: string,
  path = '/',
  init: { headers?: Record<string, string>; cookie?: string } = {}
) {
  return new NextRequest(`http://${host}${path}`, {
    headers: { host, ...(init.cookie ? { cookie: init.cookie } : {}), ...init.headers },
  });
}

const rewriteTarget = (response: Response) => response.headers.get('x-middleware-rewrite');
const overridden = (response: Response, name: string) =>
  response.headers.get(`x-middleware-request-${name}`);

describe('proxy store subdomains', () => {
  beforeEach(() => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.test');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('rewrites the store root to the storefront route and marks the slug', async () => {
    const response = await proxy(request('acme.storecart.test'));

    expect(new URL(rewriteTarget(response)!).pathname).toBe('/storefront/acme');
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
  });

  it('keeps the path and query under the store prefix', async () => {
    const response = await proxy(request('acme.storecart.test', '/products?x=1'));

    const target = new URL(rewriteTarget(response)!);
    expect(target.pathname).toBe('/storefront/acme/products');
    expect(target.search).toBe('?x=1');
  });

  it('works on *.localhost with a port when the root domain is the default', async () => {
    vi.unstubAllEnvs();
    const response = await proxy(request('acme.localhost:3000'));

    expect(new URL(rewriteTarget(response)!).pathname).toBe('/storefront/acme');
  });

  it('does not expose root-domain routes on a store host', async () => {
    for (const path of ['/dashboard', '/admin', '/login', '/api/health']) {
      const response = await proxy(request('acme.storecart.test', path));
      expect(new URL(rewriteTarget(response)!).pathname).toBe(`/storefront/acme${path}`);
    }
  });

  it('does not apply root-domain auth redirects on a store host', async () => {
    const response = await proxy(
      request('acme.storecart.test', '/login', { cookie: 'session=abc' })
    );
    expect(response.status).toBe(200);
    expect(response.headers.get('location')).toBeNull();
  });

  it('overrides a client-supplied slug marker on a store host', async () => {
    const response = await proxy(
      request('acme.storecart.test', '/', { headers: { [STORE_SLUG_HEADER]: 'victim' } })
    );
    expect(overridden(response, STORE_SLUG_HEADER)).toBe('acme');
  });

  it('adds the security headers to the rewrite', async () => {
    const response = await proxy(request('acme.storecart.test'));
    expect(response.headers.get('X-Frame-Options')).toBe('DENY');
    expect(response.headers.get('X-Content-Type-Options')).toBe('nosniff');
  });

  it.each([
    'www.storecart.test',
    'app.storecart.test',
    'admin.storecart.test',
    'api.storecart.test',
  ])('treats %s as the platform, not a store', async (host) => {
    const response = await proxy(request(host));
    expect(rewriteTarget(response)).toBeNull();
  });

  it.each(['storecart.test', '127.0.0.1:3000', 'acme.example.com', 'a.b.storecart.test'])(
    'does not rewrite %s',
    async (host) => {
      expect(rewriteTarget(await proxy(request(host)))).toBeNull();
    }
  );
});

describe('proxy root-domain behaviour is unchanged', () => {
  beforeEach(() => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.test');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('redirects an unauthenticated dashboard visit to login', async () => {
    const response = await proxy(request('storecart.test', '/dashboard'));
    expect(response.status).toBe(307);
    expect(new URL(response.headers.get('location')!).pathname).toBe('/login');
  });

  it('redirects an unauthenticated admin visit to login', async () => {
    const response = await proxy(request('storecart.test', '/admin/users'));
    expect(new URL(response.headers.get('location')!).pathname).toBe('/login');
  });

  it('redirects a signed-in user away from login', async () => {
    const response = await proxy(request('storecart.test', '/login', { cookie: 'session=abc' }));
    expect(new URL(response.headers.get('location')!).pathname).toBe('/dashboard');
  });

  it('lets a signed-in user reach the dashboard', async () => {
    const response = await proxy(
      request('storecart.test', '/dashboard', { cookie: 'session=abc' })
    );
    expect(response.status).toBe(200);
  });

  it('rejects an unauthenticated protected API call', async () => {
    expect((await proxy(request('storecart.test', '/api/profile'))).status).toBe(401);
  });

  it('keeps API CORS and security headers', async () => {
    const response = await proxy(request('storecart.test', '/api/health'));
    expect(response.headers.get('Access-Control-Allow-Methods')).toContain('GET');
    expect(response.headers.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin');
  });

  it('strips a client-supplied slug marker so /storefront/<slug> cannot be forged', async () => {
    const response = await proxy(
      request('storecart.test', '/storefront/acme', { headers: { [STORE_SLUG_HEADER]: 'acme' } })
    );
    // KAN-75: the cached storefront pages cannot check the marker, so the proxy sends direct hits to the 404.
    expect(new URL(rewriteTarget(response)!).pathname).toBe('/storefront-preview/not_found');
    expect(response.headers.get('x-middleware-override-headers') ?? '').not.toContain(
      STORE_SLUG_HEADER
    );
    expect(overridden(response, STORE_SLUG_HEADER)).toBeNull();
  });
});

describe('proxy store host extras', () => {
  beforeEach(() => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.test');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('rewrites a signed-in /login visit on a store host instead of redirecting', async () => {
    const response = await proxy(
      request('acme.storecart.test', '/login', { cookie: 'session=abc' })
    );
    expect(new URL(rewriteTarget(response)!).pathname).toBe('/storefront/acme/login');
  });

  it('applies no API CORS headers or auth gate to /api on a store host', async () => {
    const response = await proxy(request('acme.storecart.test', '/api/profile'));
    expect(response.status).toBe(200);
    expect(response.headers.get('Access-Control-Allow-Methods')).toBeNull();
  });

  it('handles an upper-case, trailing-dot host with a port', async () => {
    const response = await proxy(request('ACME.StoreCart.Test.:3000'));
    expect(new URL(rewriteTarget(response)!).pathname).toBe('/storefront/acme');
  });
});
