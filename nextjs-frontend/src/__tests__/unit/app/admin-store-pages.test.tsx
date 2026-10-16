// @vitest-environment node
/**
 * KAN-63: the admin stores and organisations pages read through the admin stores wrapper, validate their query
 * params before forwarding them, page with the right offsets and show curated errors.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const mocks = vi.hoisted(() => ({
  fetchAdminStores: vi.fn(),
  fetchAdminOrganizations: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/admin-stores', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/admin-stores')>('@/lib/api/admin-stores');
  return {
    ...actual,
    fetchAdminStores: mocks.fetchAdminStores,
    fetchAdminOrganizations: mocks.fetchAdminOrganizations,
  };
});
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/app/(admin)/admin/stores/store-row-actions', () => ({
  StoreRowActions: ({ storeId, status }: { storeId: string; status: string }) => (
    <span data-row-actions={`${storeId}:${status}`} />
  ),
}));

import AdminStoresPage from '@/app/(admin)/admin/stores/page';
import AdminOrganizationsPage from '@/app/(admin)/admin/organizations/page';

const html = (node: React.ReactNode) => renderToStaticMarkup(node as React.ReactElement);
const ok = <T,>(data: T) => ({ success: true as const, data });
const render = async (page: typeof AdminStoresPage, params: Record<string, string | undefined>) =>
  html(await page({ searchParams: Promise.resolve(params) }));

const STORE = {
  id: 'store-1',
  organization_id: 'org-1',
  organization_name: 'Acme Ltd',
  name: 'Acme Shop',
  slug: 'acme-shop',
  status: 'SUSPENDED',
  schema_version: 4,
  created_at: '2026-03-05T00:00:00Z',
  updated_at: '2026-03-06T00:00:00Z',
};
const ORG = {
  id: 'org-1',
  name: 'Acme Ltd',
  slug: 'acme',
  store_count: 2,
  created_at: '2026-03-05T00:00:00Z',
};
const storesPage = (stores: unknown[], total = stores.length) =>
  ok({ stores, total_count: total, limit: 20, offset: 0 });
const orgsPage = (organizations: unknown[], total = organizations.length) =>
  ok({ organizations, total_count: total, limit: 20, offset: 0 });

describe('admin stores page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders each store with status, schema version, organisation and actions', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([STORE]));

    const markup = await render(AdminStoresPage, {});

    expect(markup).toContain('All Stores (1)');
    expect(markup).toContain('Acme Shop');
    expect(markup).toContain('acme-shop');
    expect(markup).toContain('Acme Ltd');
    expect(markup).toContain('Suspended');
    expect(markup).toContain('Schema version');
    expect(markup).toContain('>4<');
    expect(markup).toContain('05/03/2026');
    expect(markup).toContain('data-row-actions="store-1:SUSPENDED"');
  });

  it('forwards a trimmed search, a known status and a valid organisation id', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([STORE]));

    const markup = await render(AdminStoresPage, {
      q: '  acme  ',
      status: 'ACTIVE',
      org: 'org-1',
      page: '3',
    });

    expect(mocks.fetchAdminStores).toHaveBeenCalledWith({
      search: 'acme',
      status: 'ACTIVE',
      organizationId: 'org-1',
      limit: 20,
      offset: 40,
    });
    expect(markup).toContain('Showing the stores of');
    expect(markup).toContain('Acme Ltd');
    expect(markup).toContain('name="org"');
  });

  it('drops an unknown status and a malformed organisation id, and caps the search', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([]));

    await render(AdminStoresPage, {
      q: 'x'.repeat(300),
      status: 'NOT_A_STATUS',
      org: '../admin/users',
    });

    const call = mocks.fetchAdminStores.mock.calls[0][0];
    expect(call.status).toBeUndefined();
    expect(call.organizationId).toBeUndefined();
    expect(call.search).toHaveLength(100);
  });

  it.each([
    [undefined, 0],
    ['0', 0],
    ['-4', 0],
    ['abc', 0],
    ['2', 20],
    ['99999999999999999', 9999 * 20],
  ])('page %s uses offset %s', async (page, offset) => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([]));

    await render(AdminStoresPage, { page });

    expect(mocks.fetchAdminStores.mock.calls[0][0].offset).toBe(offset);
  });

  it('shows an empty state without paging links', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([]));

    const markup = await render(AdminStoresPage, {});

    expect(markup).toContain('No stores found');
    expect(markup).not.toContain('Pagination');
  });

  it('links Next only while more rows remain, and keeps the filters', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([STORE], 21));
    const first = await render(AdminStoresPage, { q: 'acme', status: 'ACTIVE' });
    expect(first).toContain('href="/admin/stores?q=acme&amp;status=ACTIVE&amp;page=2"');
    expect(first).not.toContain('Previous');

    const second = await render(AdminStoresPage, { q: 'acme', page: '2' });
    expect(second).toContain('Previous');
    expect(second).toContain('href="/admin/stores?q=acme"');
    expect(second).not.toContain('>Next<');
  });

  it('has no paging links when the rows exactly fill the page', async () => {
    mocks.fetchAdminStores.mockResolvedValue(storesPage([STORE], 20));

    expect(await render(AdminStoresPage, {})).not.toContain('Pagination');
  });

  it.each([
    [403, 'You do not have permission to do that'],
    [404, 'Store not found'],
    [500, 'Something went wrong. Please try again.'],
    [undefined, 'The admin service is unavailable. Please try again later.'],
  ])('a %s answer shows a curated alert and logs', async (status, message) => {
    mocks.fetchAdminStores.mockResolvedValue({ success: false, error: 'SECRET', status });

    const markup = await render(AdminStoresPage, {});

    expect(markup).toContain('role="alert"');
    expect(markup).toContain(message);
    expect(markup).not.toContain('SECRET');
    expect(mocks.logError).toHaveBeenCalledWith('Admin stores page: list failed', { status });
  });
});

describe('admin organisations page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders organisations with their store count and a link to their stores', async () => {
    mocks.fetchAdminOrganizations.mockResolvedValue(orgsPage([ORG]));

    const markup = await render(AdminOrganizationsPage, {});

    expect(markup).toContain('All Organisations (1)');
    expect(markup).toContain('Acme Ltd');
    expect(markup).toContain('>2<');
    expect(markup).toContain('href="/admin/stores?org=org-1"');
    expect(markup).toContain('aria-label="View stores of Acme Ltd"');
  });

  it('trims and caps the search and pages by offset', async () => {
    mocks.fetchAdminOrganizations.mockResolvedValue(orgsPage([]));

    await render(AdminOrganizationsPage, { q: '  acme  ', page: '2' });
    await render(AdminOrganizationsPage, { q: 'y'.repeat(300) });

    expect(mocks.fetchAdminOrganizations.mock.calls[0][0]).toEqual({
      search: 'acme',
      limit: 20,
      offset: 20,
    });
    expect(mocks.fetchAdminOrganizations.mock.calls[1][0].search).toHaveLength(100);
  });

  it('shows an empty state and a curated error', async () => {
    mocks.fetchAdminOrganizations.mockResolvedValue(orgsPage([]));
    expect(await render(AdminOrganizationsPage, {})).toContain('No organisations found');

    mocks.fetchAdminOrganizations.mockResolvedValue({
      success: false,
      error: 'SECRET',
      status: 403,
    });
    const markup = await render(AdminOrganizationsPage, {});
    expect(markup).toContain('You do not have permission to do that');
    expect(markup).not.toContain('SECRET');
    expect(mocks.logError).toHaveBeenCalledWith('Admin organisations page: list failed', {
      status: 403,
    });
  });

  it('links Next while more rows remain', async () => {
    mocks.fetchAdminOrganizations.mockResolvedValue(orgsPage([ORG], 45));

    const markup = await render(AdminOrganizationsPage, { q: 'a' });

    expect(markup).toContain('href="/admin/organizations?q=a&amp;page=2"');
  });
});
