// @vitest-environment node
/** KAN-60: the onboarding wrapper creates an organisation then a store, and stays resumable when the second step fails. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  callBackend: vi.fn(),
  createOrganization: vi.fn(),
  createStore: vi.fn(),
  listOrganizations: vi.fn(),
  readStore: vi.fn(),
}));
vi.mock('server-only', () => ({}));
vi.mock('@/lib/api/server', () => ({ callBackend: mocks.callBackend }));
vi.mock('@/lib/api/generated', () => ({
  createOrganization: mocks.createOrganization,
  createStore: mocks.createStore,
  listOrganizations: mocks.listOrganizations,
  readStore: mocks.readStore,
}));

import {
  createOrganizationWithStore,
  fetchOnboardingState,
  fetchStoreStatus,
} from '@/lib/api/onboarding';

const INPUT = {
  organizationName: 'Acme',
  organizationSlug: 'acme',
  storeName: 'Acme Shop',
  storeSlug: 'acme-shop',
};
const store = (status = 'PROVISIONING') => ({
  id: 'st1',
  organization_id: 'org1',
  name: 'Acme Shop',
  slug: 'acme-shop',
  status,
  created_at: '',
  updated_at: '',
});
const org = (over: Record<string, unknown> = {}) => ({
  id: 'org1',
  name: 'Acme',
  slug: 'acme',
  role: 'OWNER',
  created_at: '',
  updated_at: '',
  stores: [],
  stores_truncated: false,
  ...over,
});
const ok = (data: unknown) => ({ success: true as const, data });
const fail = (status: number, error = 'x') => ({ success: false as const, status, error });

/** Runs each SDK closure (so its arguments are recorded) and answers with the queued result. */
function queue(...results: unknown[]) {
  const pending = [...results];
  mocks.callBackend.mockImplementation(async (call: (client: unknown) => Promise<unknown>) => {
    await call({ marker: 'client' });
    return pending.shift();
  });
}

describe('createOrganizationWithStore', () => {
  beforeEach(() => vi.resetAllMocks());

  it('passes the id of the organisation it created to createStore, with the store fields', async () => {
    queue(ok([]), ok(org({ id: 'org-created' })), ok(store()));
    await createOrganizationWithStore(INPUT);
    expect(mocks.createOrganization).toHaveBeenCalledWith(
      expect.objectContaining({ body: { name: 'Acme', slug: 'acme' } })
    );
    expect(mocks.createStore).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { organization_id: 'org-created' },
        body: { name: 'Acme Shop', slug: 'acme-shop' },
      })
    );
  });

  it('passes the id of the reused organisation to createStore and creates no organisation', async () => {
    queue(ok([org({ id: 'org-existing' })]), ok(store()));
    await createOrganizationWithStore({ storeName: 'Acme Shop', storeSlug: 'acme-shop' });
    expect(mocks.createOrganization).not.toHaveBeenCalled();
    expect(mocks.createStore).toHaveBeenCalledWith(
      expect.objectContaining({ path: { organization_id: 'org-existing' } })
    );
  });

  it('refuses a store-only request when there is no organisation to reuse', async () => {
    queue(ok([]));
    expect(
      await createOrganizationWithStore({ storeName: 'Acme Shop', storeSlug: 'acme-shop' })
    ).toEqual({ success: false, reason: 'invalid', stage: 'organization' });
    expect(mocks.createOrganization).not.toHaveBeenCalled();
    expect(mocks.createStore).not.toHaveBeenCalled();
  });

  it('creates the organisation then the store, which starts PROVISIONING', async () => {
    mocks.callBackend
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce(ok(org()))
      .mockResolvedValueOnce(ok(store()));
    expect(await createOrganizationWithStore(INPUT)).toEqual({
      success: true,
      storeId: 'st1',
      organizationId: 'org1',
      resumed: false,
    });
    expect(mocks.callBackend).toHaveBeenCalledTimes(3);
  });

  it('reuses an existing empty organisation instead of creating a second one', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok([org()])).mockResolvedValueOnce(ok(store()));
    const result = await createOrganizationWithStore(INPUT);
    expect(result).toMatchObject({ success: true, organizationId: 'org1', resumed: true });
    expect(mocks.callBackend).toHaveBeenCalledTimes(2);
  });

  it('refuses when the user already has a store', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok([org({ stores: [store('ACTIVE')] })]));
    expect(await createOrganizationWithStore(INPUT)).toMatchObject({
      success: false,
      reason: 'already_onboarded',
    });
    expect(mocks.callBackend).toHaveBeenCalledTimes(1);
  });

  it('does not reuse an organisation the user does not own', async () => {
    mocks.callBackend
      .mockResolvedValueOnce(ok([org({ role: 'STAFF' })]))
      .mockResolvedValueOnce(ok(org({ id: 'org2' })))
      .mockResolvedValueOnce(ok(store()));
    expect(await createOrganizationWithStore(INPUT)).toMatchObject({ organizationId: 'org2' });
  });

  it.each([
    [409, 'Slug is already taken', 'slug_taken'],
    [422, 'bad', 'invalid'],
    [409, 'Plan limit reached', 'limit'],
    [403, 'Forbidden', 'limit'],
    [401, 'nope', 'unauthorized'],
    [500, 'boom', 'unavailable'],
  ])('maps organisation step %s "%s" to %s', async (status, error, reason) => {
    mocks.callBackend.mockResolvedValueOnce(ok([])).mockResolvedValueOnce(fail(status, error));
    expect(await createOrganizationWithStore(INPUT)).toEqual({
      success: false,
      reason,
      stage: 'organization',
    });
  });

  it('reports the organisation id when it was created but the store failed, so a retry resumes', async () => {
    mocks.callBackend
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce(ok(org()))
      .mockResolvedValueOnce(fail(409, 'Slug is already taken'));
    expect(await createOrganizationWithStore(INPUT)).toEqual({
      success: false,
      reason: 'slug_taken',
      stage: 'store',
      organizationId: 'org1',
    });
  });

  it('treats an unreachable backend while listing as unavailable', async () => {
    mocks.callBackend.mockResolvedValueOnce({ success: false, error: 'Backend unavailable' });
    expect(await createOrganizationWithStore(INPUT)).toMatchObject({
      success: false,
      reason: 'unavailable',
    });
  });
});

describe('fetchOnboardingState', () => {
  beforeEach(() => vi.resetAllMocks());

  it('is new with no organisations', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok([]));
    expect(await fetchOnboardingState()).toEqual({ success: true, data: { kind: 'new' } });
  });

  it('is resumable with an owned empty organisation', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok([org()]));
    expect(await fetchOnboardingState()).toEqual({
      success: true,
      data: { kind: 'resume', organizationName: 'Acme' },
    });
  });

  it('is done once any store exists', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok([org({ stores: [store('ACTIVE')] })]));
    expect(await fetchOnboardingState()).toEqual({ success: true, data: { kind: 'done' } });
  });

  it('passes a backend failure through', async () => {
    mocks.callBackend.mockResolvedValueOnce(fail(500));
    expect((await fetchOnboardingState()).success).toBe(false);
  });
});

describe('fetchStoreStatus', () => {
  beforeEach(() => vi.resetAllMocks());

  it('returns the store name and status', async () => {
    mocks.callBackend.mockResolvedValueOnce(ok(store('PROVISIONING')));
    expect(await fetchStoreStatus('st1')).toEqual({
      success: true,
      data: { id: 'st1', name: 'Acme Shop', status: 'PROVISIONING' },
    });
  });

  it.each([403, 404])('reports not_found for %s, hiding other tenants', async (status) => {
    mocks.callBackend.mockResolvedValueOnce(fail(status));
    expect(await fetchStoreStatus('st1')).toEqual({ success: false, reason: 'not_found' });
  });

  it('reports unavailable for other failures', async () => {
    mocks.callBackend.mockResolvedValueOnce(fail(500));
    expect(await fetchStoreStatus('st1')).toEqual({ success: false, reason: 'unavailable' });
  });
});
