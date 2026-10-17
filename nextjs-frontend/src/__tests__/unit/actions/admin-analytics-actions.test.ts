// @vitest-environment node
/**
 * KAN-119: the sync action returns the drift report, answers failures with curated messages (never backend
 * text) and refreshes the subscriptions page after a successful run.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  syncAdminSubscriptions: vi.fn(),
  revalidatePath: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/admin-analytics', () => ({
  syncAdminSubscriptions: mocks.syncAdminSubscriptions,
}));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));

import { syncStripeSubscriptionsAction } from '@/app/actions/admin/analytics-actions';
import {
  ADMIN_SYNC_RATE_LIMITED_MESSAGE,
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
} from '@/lib/api/admin-errors';

const SECRET = 'SECRET-sk_live_abc123';

describe('syncStripeSubscriptionsAction', () => {
  beforeEach(() => vi.clearAllMocks());

  it('tells the admin to wait when the sync is rate limited', async () => {
    mocks.syncAdminSubscriptions.mockResolvedValue({ success: false, error: SECRET, status: 429 });

    const result = await syncStripeSubscriptionsAction();

    expect(result).toEqual({ success: false, error: ADMIN_SYNC_RATE_LIMITED_MESSAGE });
  });

  it('returns the report and revalidates the subscriptions page', async () => {
    const data = { stripe_subscriptions: 3, in_sync: 3, drift_count: 0, drifts: [] };
    mocks.syncAdminSubscriptions.mockResolvedValue({ success: true, data });

    const result = await syncStripeSubscriptionsAction();

    expect(result).toEqual({ success: true, data });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/admin/subscriptions');
  });

  it.each([
    [403, ADMIN_FORBIDDEN_MESSAGE, false],
    [401, ADMIN_FORBIDDEN_MESSAGE, false],
    [502, ADMIN_REQUEST_FAILED_MESSAGE, true],
    [undefined, ADMIN_UNAVAILABLE_MESSAGE, true],
  ])(
    'status %s gives a curated message (logged: %s) and no revalidation',
    async (status, message, logged) => {
      mocks.syncAdminSubscriptions.mockResolvedValue({ success: false, error: SECRET, status });

      const result = await syncStripeSubscriptionsAction();

      expect(result).toEqual({ success: false, error: message });
      expect(JSON.stringify(result)).not.toContain('SECRET');
      expect(mocks.logError).toHaveBeenCalledTimes(logged ? 1 : 0);
      expect(mocks.revalidatePath).not.toHaveBeenCalled();
    }
  );
});
