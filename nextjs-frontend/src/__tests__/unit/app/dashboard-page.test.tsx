// @vitest-environment node
/**
 * KAN-41: the dashboard home page reads profile and login history through the API; only the plan still
 * comes from the legacy billing row, and a user without one is on the free plan.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { navigationMock, redirectTarget, rejection } from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  fetchProfile: vi.fn(),
  fetchLoginHistory: vi.fn(),
  billingFindUnique: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/db/client', () => ({ db: { user: { findUnique: mocks.billingFindUnique } } }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/dashboard/subscription-success-handler', () => ({
  SubscriptionSuccessHandler: () => null,
}));
vi.mock('@/lib/api/account', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/account')>('@/lib/api/account');
  return {
    toProfile: actual.toProfile,
    toLoginHistoryEntry: actual.toLoginHistoryEntry,
    fetchProfile: mocks.fetchProfile,
    fetchLoginHistory: mocks.fetchLoginHistory,
  };
});

import DashboardPage from '@/app/dashboard/page';

const PROFILE = {
  id: 'u1',
  email: 'a@b.test',
  email_verified: true,
  display_name: 'Ada',
  bio: null,
  avatar_url: null,
  location: null,
  website: null,
  phone_number: null,
  created_at: '2026-01-01T00:00:00Z',
};
const HISTORY = {
  login_history: [
    {
      id: 'h1',
      ip_address: '203.0.113.9',
      user_agent: 'UA',
      location: null,
      login_at: '2026-01-02T03:04:05Z',
      successful: true,
    },
  ],
  total_count: 7,
};
const page = () => DashboardPage({ searchParams: Promise.resolve({}) });

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: true });
    mocks.fetchProfile.mockResolvedValue({ success: true, data: PROFILE });
    mocks.fetchLoginHistory.mockResolvedValue({ success: true, data: HISTORY });
    mocks.billingFindUnique.mockResolvedValue({
      subscriptionTier: 'pro',
      subscriptionStatus: 'active',
      stripeCurrentPeriodEnd: new Date('2027-01-01T00:00:00Z'),
    });
  });

  it('redirects to /login with no session cookie', async () => {
    mocks.cookieGet.mockReturnValue(undefined);

    expect(redirectTarget(await rejection(page()))).toBe('/login');
  });

  it('renders from the API data and asks for the five most recent logins', async () => {
    const tree = await page();

    expect(tree).toBeDefined();
    expect(mocks.fetchLoginHistory).toHaveBeenCalledWith(5, 0);
    expect(mocks.billingFindUnique).toHaveBeenCalledWith(
      expect.objectContaining({ where: { firebaseUid: 'uid-1' } })
    );
  });

  it('treats a user without a legacy billing row as free instead of failing', async () => {
    mocks.billingFindUnique.mockResolvedValue(null);

    await expect(page()).resolves.toBeDefined();
  });

  it('sends an unverified user to /verify-email', async () => {
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: false });

    expect(redirectTarget(await rejection(page()))).toBe('/verify-email');
  });

  it.each([
    [401, 'Invalid authentication'],
    [404, 'Not found'],
  ])('clears the session when the backend answers %s', async (status, error) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, error, status });

    expect(redirectTarget(await rejection(page()))).toBe('/api/auth/clear-session');
  });

  it('clears the session when the Firebase session cookie is revoked', async () => {
    mocks.verifySessionCookie.mockRejectedValue(
      Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' })
    );

    expect(redirectTarget(await rejection(page()))).toBe('/api/auth/clear-session');
  });

  it.each([
    [{ success: false, error: 'Backend unavailable' }, 'unreachable'],
    [{ success: false, error: 'Unauthorized', status: 401 }, '401'],
    [{ success: false, error: 'Request failed', status: 500 }, '500'],
  ])('keeps the session and rethrows on an outage (%o)', async (failure, detail) => {
    mocks.fetchLoginHistory.mockResolvedValue(failure);

    const error = await rejection(page());

    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(String(error)).toContain(detail);
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
  });
});
