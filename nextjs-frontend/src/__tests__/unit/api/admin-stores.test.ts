// @vitest-environment node
/**
 * KAN-63: the admin stores wrappers call the /v1/admin/organizations and /v1/admin/stores routes with the
 * session cookie and the internal key, and map failures to curated messages that never carry backend text.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_MIGRATION_FAILED_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_STORE_CONFLICT_MESSAGE,
  ADMIN_STORE_NOT_FOUND_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
  adminErrorMessage,
  fetchAdminOrganizations,
  fetchAdminStores,
  migrateAdminStore,
  suspendAdminStore,
  unsuspendAdminStore,
} from '@/lib/api/admin-stores';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const STORE = {
  id: 'store-1',
  organization_id: 'org-1',
  organization_name: 'Acme',
  name: 'Acme Shop',
  slug: 'acme',
  status: 'ACTIVE',
  schema_version: 3,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

const fail = (status?: number) => ({ success: false as const, error: 'SECRET detail', status });

describe('admin stores wrappers', () => {
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

  it('fetchAdminStores sends filters, a trimmed search and the session headers', async () => {
    const page = { stores: [STORE], total_count: 1, limit: 20, offset: 20 };
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: page }));

    const result = await fetchAdminStores({
      search: '  acme  ',
      status: 'SUSPENDED',
      organizationId: 'org-1',
      offset: 20,
    });

    expect(result).toEqual({ success: true, data: page });
    const request = fetchMock.mock.calls[0][0];
    const url = new URL(request.url);
    expect(url.pathname).toBe('/v1/admin/stores');
    expect(url.searchParams.get('search')).toBe('acme');
    expect(url.searchParams.get('status')).toBe('SUSPENDED');
    expect(url.searchParams.get('organization_id')).toBe('org-1');
    expect(url.searchParams.get('limit')).toBe('20');
    expect(url.searchParams.get('offset')).toBe('20');
    expect(request.headers.get('X-Session-Token')).toBe('firebase-session-cookie');
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('fetchAdminStores omits empty filters and caps the search length', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: true, data: { stores: [], total_count: 0, limit: 20, offset: 0 } })
    );

    await fetchAdminStores({ search: '   ' });
    await fetchAdminStores({ search: 'x'.repeat(500) });

    const first = new URL(fetchMock.mock.calls[0][0].url).searchParams;
    expect(first.has('search')).toBe(false);
    expect(first.has('status')).toBe(false);
    expect(first.has('organization_id')).toBe(false);
    expect(new URL(fetchMock.mock.calls[1][0].url).searchParams.get('search')).toHaveLength(100);
  });

  it('fetchAdminOrganizations lists organisations with paging and search', async () => {
    const page = {
      organizations: [
        {
          id: 'org-1',
          name: 'Acme',
          slug: 'acme',
          store_count: 2,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      total_count: 1,
      limit: 20,
      offset: 0,
    };
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: page }));

    const result = await fetchAdminOrganizations({ search: 'acme' });

    expect(result).toEqual({ success: true, data: page });
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/v1/admin/organizations');
    expect(url.searchParams.get('search')).toBe('acme');
  });

  it.each([
    ['suspendAdminStore', () => suspendAdminStore('store-1'), '/v1/admin/stores/store-1/suspend'],
    [
      'unsuspendAdminStore',
      () => unsuspendAdminStore('store-1'),
      '/v1/admin/stores/store-1/unsuspend',
    ],
    ['migrateAdminStore', () => migrateAdminStore('store-1'), '/v1/admin/stores/store-1/migrate'],
  ])('%s POSTs %s', async (_name, call, path) => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true, data: {} }));

    await call();

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe(path);
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('a backend error becomes a failed result carrying the status', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'nope' }, 409));

    const result = await suspendAdminStore('store-1');

    expect(result).toMatchObject({ success: false, status: 409 });
  });

  describe('adminErrorMessage', () => {
    it.each([
      [401, ADMIN_FORBIDDEN_MESSAGE],
      [403, ADMIN_FORBIDDEN_MESSAGE],
      [404, ADMIN_STORE_NOT_FOUND_MESSAGE],
      [409, ADMIN_STORE_CONFLICT_MESSAGE],
      [422, ADMIN_REQUEST_FAILED_MESSAGE],
      [502, ADMIN_REQUEST_FAILED_MESSAGE],
      [503, ADMIN_REQUEST_FAILED_MESSAGE],
      [undefined, ADMIN_UNAVAILABLE_MESSAGE],
    ])('status %s gives a fixed message', (status, message) => {
      expect(adminErrorMessage(fail(status))).toBe(message);
    });

    it('words 502 and 503 as a re-runnable failure for migrations only', () => {
      expect(adminErrorMessage(fail(502), { migration: true })).toBe(
        ADMIN_MIGRATION_FAILED_MESSAGE
      );
      expect(adminErrorMessage(fail(503), { migration: true })).toBe(
        ADMIN_MIGRATION_FAILED_MESSAGE
      );
      expect(adminErrorMessage(fail(403), { migration: true })).toBe(ADMIN_FORBIDDEN_MESSAGE);
    });

    it('never passes backend text through', () => {
      for (const status of [401, 404, 409, 500, 502, undefined]) {
        expect(adminErrorMessage(fail(status), { migration: true })).not.toContain('SECRET');
      }
    });
  });
});
