// @vitest-environment node
/** KAN-64: the storefront wrapper maps the backend lookup to a store or null, and fails loudly otherwise. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const headerGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: vi.fn() })),
  headers: vi.fn(async () => ({ get: headerGet })),
}));

import { fetchStorefront, STOREFRONT_LOOKUP_FAILED_MESSAGE } from '@/lib/api/storefront';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('fetchStorefront', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    headerGet.mockReset();
  });

  it('returns only the public fields of an active store', async () => {
    fetchMock.mockResolvedValue(
      json({ success: true, data: { name: 'Acme', slug: 'acme', database_ref: 'secret' } })
    );

    const store = await fetchStorefront('acme');

    expect(store).toEqual({ name: 'Acme', slug: 'acme' });
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/v1/storefront/acme');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('forwards the visitor IP as X-Client-IP on Vercel', async () => {
    vi.stubEnv('VERCEL', '1');
    headerGet.mockImplementation((name: string) =>
      name === 'x-vercel-forwarded-for' ? '203.0.113.9' : null
    );
    fetchMock.mockResolvedValue(json({ success: true, data: { name: 'Acme', slug: 'acme' } }));

    await fetchStorefront('acme');

    expect(fetchMock.mock.calls[0][0].headers.get('X-Client-IP')).toBe('203.0.113.9');
  });

  it('returns null for a 404 without trusting any body', async () => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'Store not found' }, 404));
    expect(await fetchStorefront('ghost')).toBeNull();
  });

  it.each(['../etc', 'AB', 'www', 'a.b', 'ac%2fme', ''])(
    'returns null for %j without calling the backend',
    async (slug) => {
      expect(await fetchStorefront(slug)).toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );

  it.each([429, 500, 401])(
    'throws on backend status %i instead of reporting a missing store',
    async (status) => {
      fetchMock.mockResolvedValue(json({ success: false, error: 'nope' }, status));
      await expect(fetchStorefront('acme')).rejects.toThrow(STOREFRONT_LOOKUP_FAILED_MESSAGE);
    }
  );

  it('throws when the backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    await expect(fetchStorefront('acme')).rejects.toThrow(STOREFRONT_LOOKUP_FAILED_MESSAGE);
  });
});
