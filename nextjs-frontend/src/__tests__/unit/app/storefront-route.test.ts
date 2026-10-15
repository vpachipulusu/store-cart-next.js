// @vitest-environment node
/** KAN-64: the storefront route shows only public fields and 404s unless the proxy rewrote to this slug. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const headerGet = vi.fn();
vi.mock('next/headers', () => ({ headers: vi.fn(async () => ({ get: headerGet })) }));

const fetchStorefront = vi.fn();
vi.mock('@/lib/api/storefront', () => ({
  fetchStorefront: (slug: string) => fetchStorefront(slug),
}));

import { GET } from '@/app/storefront/[slug]/route';
import { escapeHtml } from '@/lib/storefront/html';

const call = (slug: string) =>
  GET(new Request(`http://x/storefront/${slug}`), { params: Promise.resolve({ slug }) });

describe('storefront route', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    headerGet.mockReturnValue('acme');
  });

  it('renders the store name with a 200', async () => {
    fetchStorefront.mockResolvedValue({ name: 'Acme Goods', slug: 'acme' });

    const response = await call('acme');
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(body).toContain('<h1>Acme Goods</h1>');
    expect(body).toContain('<title>Acme Goods</title>');
    expect(fetchStorefront).toHaveBeenCalledWith('acme');
  });

  it('escapes the store name instead of rendering markup', async () => {
    fetchStorefront.mockResolvedValue({ name: '<img src=x onerror=alert(1)>"\'&', slug: 'acme' });

    const body = await (await call('acme')).text();

    expect(body).not.toContain('<img');
    expect(body).toContain('&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;');
  });

  it('404s an unknown or suspended store with a noindex body that does not echo the slug', async () => {
    fetchStorefront.mockResolvedValue(null);

    const response = await call('ghost');
    const body = await response.text();

    expect(response.status).toBe(404);
    expect(body).toContain('noindex');
    expect(body).not.toContain('ghost');
  });

  it('404s without a lookup when the proxy marker is missing', async () => {
    headerGet.mockReturnValue(null);
    expect((await call('acme')).status).toBe(404);
    expect(fetchStorefront).not.toHaveBeenCalled();
  });

  it('404s without a lookup when the marker names a different store', async () => {
    headerGet.mockReturnValue('other');
    expect((await call('acme')).status).toBe(404);
    expect(fetchStorefront).not.toHaveBeenCalled();
  });

  it('answers 503, not 404, when the lookup fails', async () => {
    fetchStorefront.mockRejectedValue(new Error('Storefront lookup failed'));

    const response = await call('acme');

    expect(response.status).toBe(503);
    expect(response.headers.get('Retry-After')).toBe('30');
  });
});

describe('escapeHtml', () => {
  it('leaves plain text alone', () => {
    expect(escapeHtml('Acme Goods 2')).toBe('Acme Goods 2');
  });
});
