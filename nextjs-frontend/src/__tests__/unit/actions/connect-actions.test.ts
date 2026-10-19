// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const APP_ORIGIN = 'https://shop.example.test';

const mocks = vi.hoisted(() => ({
  fetchConnectStatus: vi.fn(),
  startConnectOnboarding: vi.fn(),
  getVerifiedUserId: vi.fn(),
}));

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api/connect', () => ({
  NO_CONNECT_ORGANIZATION_MESSAGE: 'No organisation you can manage billing for was found',
  fetchConnectStatus: mocks.fetchConnectStatus,
  startConnectOnboarding: mocks.startConnectOnboarding,
}));

import {
  getConnectStatusAction,
  startConnectOnboardingAction,
} from '@/app/actions/connect-actions';

const NO_ORG = 'No organisation you can manage billing for was found';

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.stubEnv('NEXT_PUBLIC_APP_URL', APP_ORIGIN);
  mocks.getVerifiedUserId.mockResolvedValue('user-1');
});

describe('getConnectStatusAction', () => {
  it('maps the backend flags to camelCase', async () => {
    mocks.fetchConnectStatus.mockResolvedValue({
      success: true,
      data: {
        has_account: true,
        charges_enabled: true,
        payouts_enabled: false,
        details_submitted: true,
      },
    });

    expect(await getConnectStatusAction()).toEqual({
      success: true,
      data: {
        hasAccount: true,
        chargesEnabled: true,
        payoutsEnabled: false,
        detailsSubmitted: true,
      },
    });
  });

  it('requires a verified session', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    const result = await getConnectStatusAction();

    expect(result.success).toBe(false);
    expect(mocks.fetchConnectStatus).not.toHaveBeenCalled();
  });

  it.each([
    [NO_ORG, undefined, /create a store first/i],
    ['Forbidden', 403, /owner or admin/i],
    ['Organization not found', 404, /owner or admin/i],
    ['Billing provider unavailable', 502, /payment provider/i],
    ['Service temporarily unavailable', 503, /not available right now/i],
    ['raw backend text', 500, /could not load your payment status/i],
  ])('shows a curated message for %s (status %s)', async (error, status, expected) => {
    mocks.fetchConnectStatus.mockResolvedValue({ success: false, error, status });

    const result = await getConnectStatusAction();

    expect(result).toEqual({ success: false, error: expect.stringMatching(expected) });
    expect(JSON.stringify(result)).not.toContain('raw backend text');
  });

  it('survives a thrown error without leaking it', async () => {
    mocks.fetchConnectStatus.mockRejectedValue(new Error('secret detail'));

    const result = await getConnectStatusAction();

    expect(result.success).toBe(false);
    expect(JSON.stringify(result)).not.toContain('secret detail');
  });
});

describe('startConnectOnboardingAction', () => {
  it('builds the return and refresh URLs on the server from the app origin', async () => {
    mocks.startConnectOnboarding.mockResolvedValue({
      success: true,
      data: { url: 'https://connect.stripe.test/setup' },
    });

    const result = await startConnectOnboardingAction();

    expect(mocks.startConnectOnboarding).toHaveBeenCalledWith(
      `${APP_ORIGIN}/dashboard/settings?connect=return`,
      `${APP_ORIGIN}/dashboard/settings?connect=refresh`
    );
    expect(result).toEqual({ success: true, data: { url: 'https://connect.stripe.test/setup' } });
  });

  it('requires a verified session', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    const result = await startConnectOnboardingAction();

    expect(result.success).toBe(false);
    expect(mocks.startConnectOnboarding).not.toHaveBeenCalled();
  });

  it.each([
    [422, /could not start payment setup/i],
    [502, /payment provider/i],
    [503, /not available right now/i],
    [403, /owner or admin/i],
  ])('maps backend status %s to a curated message', async (status, expected) => {
    mocks.startConnectOnboarding.mockResolvedValue({
      success: false,
      error: 'raw backend text',
      status,
    });

    const result = await startConnectOnboardingAction();

    expect(result).toEqual({ success: false, error: expect.stringMatching(expected) });
    expect(JSON.stringify(result)).not.toContain('raw backend text');
  });

  it('fails cleanly when the app origin is not configured in production', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_APP_URL', '');

    const result = await startConnectOnboardingAction();

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/could not start payment setup/i),
    });
    expect(mocks.startConnectOnboarding).not.toHaveBeenCalled();
  });
});
