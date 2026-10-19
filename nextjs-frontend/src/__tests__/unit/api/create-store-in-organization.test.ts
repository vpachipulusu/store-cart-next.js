// @vitest-environment node
/** KAN-254: creating another store in an existing organisation maps every backend answer to a fixed reason. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  callBackend: vi.fn(),
  createStore: vi.fn(),
}));
vi.mock('server-only', () => ({}));
vi.mock('@/lib/api/server', () => ({ callBackend: mocks.callBackend }));
vi.mock('@/lib/api/generated', () => ({
  createOrganization: vi.fn(),
  createStore: mocks.createStore,
  listOrganizations: vi.fn(),
  readStore: vi.fn(),
  retryStoreProvisioning: vi.fn(),
}));

import { createStoreInOrganization } from '@/lib/api/onboarding';

const ORG_ID = 'org1';
const INPUT = { storeName: 'Second Shop', storeSlug: 'second-shop' };
const ok = (data: unknown) => ({ success: true as const, data });
const fail = (status: number, error = 'x') => ({ success: false as const, status, error });

describe('createStoreInOrganization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.callBackend.mockImplementation(async (call: (client: unknown) => Promise<unknown>) => {
      await call({ marker: 'client' });
      return ok({
        id: 'st2',
        organization_id: ORG_ID,
        name: 'Second Shop',
        slug: 'second-shop',
        status: 'PROVISIONING',
      });
    });
  });

  it('creates the store in the given organisation and returns its id, name and status', async () => {
    const result = await createStoreInOrganization(ORG_ID, INPUT);

    expect(result).toEqual({
      success: true,
      storeId: 'st2',
      name: 'Second Shop',
      status: 'PROVISIONING',
    });
    expect(mocks.createStore).toHaveBeenCalledWith({
      client: { marker: 'client' },
      path: { organization_id: ORG_ID },
      body: { name: 'Second Shop', slug: 'second-shop' },
    });
  });

  it.each([
    [409, 'Slug is already taken', 'slug_taken'],
    [409, 'Organization limit reached', 'limit'],
    [403, 'Forbidden', 'forbidden'],
    [404, 'Organization not found', 'not_found'],
    [422, 'Slug is reserved', 'invalid'],
    [401, 'nope', 'unauthorized'],
    [500, 'boom', 'unavailable'],
    [0, 'network', 'unavailable'],
  ])('maps %s "%s" to %s without forwarding the backend text', async (status, error, reason) => {
    mocks.callBackend.mockResolvedValueOnce(fail(status, error));
    expect(await createStoreInOrganization(ORG_ID, INPUT)).toEqual({ success: false, reason });
  });

  it.each([
    'The Free plan allows 1 store. Upgrade your plan to add more.',
    'The Pro plan allows 3 stores. Upgrade your plan to add more.',
  ])('passes the plan store limit message "%s" through as the upgrade message', async (error) => {
    mocks.callBackend.mockResolvedValueOnce(fail(409, error));
    expect(await createStoreInOrganization(ORG_ID, INPUT)).toEqual({
      success: false,
      reason: 'limit',
      limitMessage: error,
    });
  });

  it.each([
    'The Free plan allows 1 store. Upgrade your plan to add more. <a href="x">click</a>',
    'The Free plan allows 1 store.',
    'Plan limit reached',
  ])('does not forward a limit text that is not the known wording: "%s"', async (error) => {
    mocks.callBackend.mockResolvedValueOnce(fail(409, error));
    expect(await createStoreInOrganization(ORG_ID, INPUT)).toEqual({
      success: false,
      reason: 'limit',
    });
  });
});
