// @vitest-environment node
/** KAN-61: the stores wrapper lists the caller's organisations with the session cookie and flattens their stores. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import { fetchMerchantStores } from '@/lib/api/stores';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const storeRow = (id: string, name: string, organizationId: string) => ({
  id,
  organization_id: organizationId,
  name,
  slug: name.toLowerCase(),
  status: 'ACTIVE',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
});

const organization = (id: string, name: string, stores: ReturnType<typeof storeRow>[]) => ({
  id,
  name,
  slug: name.toLowerCase(),
  role: 'OWNER',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  stores,
  stores_truncated: false,
});

describe('fetchMerchantStores', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
  });

  it('flattens the stores of every organisation and sends the session and internal key', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        success: true,
        data: [
          organization('o1', 'Alpha', [storeRow('s1', 'One', 'o1'), storeRow('s2', 'Two', 'o1')]),
          organization('o2', 'Beta', [storeRow('s3', 'Three', 'o2')]),
          organization('o3', 'Empty', []),
        ],
      })
    );

    const result = await fetchMerchantStores();

    expect(result).toEqual({
      success: true,
      data: [
        expect.objectContaining({ id: 's1', organizationId: 'o1', organizationName: 'Alpha' }),
        expect.objectContaining({ id: 's2', organizationId: 'o1' }),
        expect.objectContaining({ id: 's3', organizationId: 'o2', organizationName: 'Beta' }),
      ],
    });
    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe('/v1/organizations');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('returns an empty list for a user with no organisations', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: [] }));
    expect(await fetchMerchantStores()).toEqual({ success: true, data: [] });
  });

  it('passes a backend rejection through with its status', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Invalid authentication' }, 401)
    );
    expect(await fetchMerchantStores()).toEqual({
      success: false,
      error: 'Invalid authentication',
      status: 401,
    });
  });

  it('fetches the full store list for a truncated organisation, page by page', async () => {
    const embedded = Array.from({ length: 100 }, (_, i) => storeRow(`e${i}`, `E${i}`, 'o1'));
    const page1 = Array.from({ length: 100 }, (_, i) => storeRow(`p${i}`, `P${i}`, 'o1'));
    const page2 = [storeRow('last', 'Last', 'o1')];
    fetchMock.mockImplementation(async (request) => {
      const url = new URL(request.url);
      if (url.pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: [
            { ...organization('o1', 'Big', embedded), stores_truncated: true },
            organization('o2', 'Small', [storeRow('s9', 'Nine', 'o2')]),
          ],
        });
      }
      expect(url.pathname).toBe('/v1/organizations/o1/stores');
      const page = url.searchParams.get('offset') === '0' ? page1 : page2;
      return jsonResponse({ success: true, data: page, total: 101, limit: 100, offset: 0 });
    });

    const result = await fetchMerchantStores();

    expect(result.success).toBe(true);
    const ids = result.success ? result.data.map((store) => store.id) : [];
    expect(ids).toHaveLength(102);
    expect(ids).toContain('last');
    expect(ids).toContain('s9');
    expect(ids).not.toContain('e0');
    // organisations call + two store pages; the untruncated organisation costs nothing extra
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('fails instead of returning a partial list when the full store list cannot be loaded', async () => {
    fetchMock.mockImplementation(async (request) => {
      if (new URL(request.url).pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: [{ ...organization('o1', 'Big', []), stores_truncated: true }],
        });
      }
      return jsonResponse({ success: false, error: 'Request failed' }, 500);
    });

    expect(await fetchMerchantStores()).toEqual({
      success: false,
      error: 'Request failed',
      status: 500,
    });
  });
});
