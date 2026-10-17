// @vitest-environment node
/** KAN-242: the wrapper behind the merchant "Retry setup" button maps backend answers to fixed reasons. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ callBackend: vi.fn(), retryStoreProvisioning: vi.fn() }));
vi.mock('server-only', () => ({}));
vi.mock('@/lib/api/server', () => ({ callBackend: mocks.callBackend }));
vi.mock('@/lib/api/generated', () => ({
  createOrganization: vi.fn(),
  createStore: vi.fn(),
  listOrganizations: vi.fn(),
  readStore: vi.fn(),
  retryStoreProvisioning: mocks.retryStoreProvisioning,
}));

import { requestProvisioningRetry } from '@/lib/api/onboarding';

const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';
const failure = (status: number | undefined, error = 'backend text') => ({
  success: false,
  error,
  ...(status === undefined ? {} : { status }),
});

describe('requestProvisioningRetry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls the generated retry route for the store through callBackend', async () => {
    mocks.callBackend.mockImplementation(
      async (call: (client: unknown) => unknown) => (await call('client'), failure(500))
    );

    await requestProvisioningRetry(STORE_ID);

    expect(mocks.retryStoreProvisioning).toHaveBeenCalledWith({
      client: 'client',
      path: { store_id: STORE_ID },
    });
  });

  it('returns the attempt number when the retry was queued', async () => {
    mocks.callBackend.mockResolvedValue({
      success: true,
      data: { store_id: STORE_ID, status: 'PROVISIONING', attempt: 2, max_attempts: 3 },
    });

    expect(await requestProvisioningRetry(STORE_ID)).toEqual({
      success: true,
      attempt: 2,
      maxAttempts: 3,
    });
  });

  it.each([
    [409, 'Provisioning retry limit reached', 'limit'],
    [409, 'Operation not allowed in the current state', 'not_failed'],
    [409, 'Provisioning retry limit exceeded', 'not_failed'],
    [409, 'The retry limit was reached', 'not_failed'],
    [401, 'Invalid authentication', 'unauthorized'],
    [403, 'Forbidden', 'forbidden'],
    [404, 'Store not found', 'not_found'],
    [429, 'Too many requests', 'rate_limited'],
    [502, 'Provisioning could not be started', 'unavailable'],
    [503, 'The result could not be recorded; retry', 'unavailable'],
    [undefined, 'fetch failed', 'unavailable'],
  ])('maps %s "%s" to %s and never forwards the backend text', async (status, error, reason) => {
    mocks.callBackend.mockResolvedValue(failure(status, error));

    const result = await requestProvisioningRetry(STORE_ID);

    expect(result).toEqual({ success: false, reason });
  });
});
