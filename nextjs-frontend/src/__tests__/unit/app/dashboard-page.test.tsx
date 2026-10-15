// @vitest-environment node
/**
 * KAN-41 / KAN-50: the dashboard home page reads profile, login history and the plan through the API; an
 * account with no billing organisation is on the free plan.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { NO_BILLING_ORGANIZATION_MESSAGE } from '@/lib/api/billing';
import { navigationMock, redirectTarget, rejection } from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  fetchProfile: vi.fn(),
  fetchLoginHistory: vi.fn(),
  fetchBillingSummary: vi.fn(),
  dbFindUnique: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
// verified-session.ts (not part of this ticket) still imports the client for its own lookups.
vi.mock('@/lib/db/client', () => ({ db: { user: { findUnique: mocks.dbFindUnique } } }));
vi.mock('@/lib/api/billing', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/billing')>('@/lib/api/billing');
  return { ...actual, fetchBillingSummary: mocks.fetchBillingSummary };
});
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
    mocks.fetchBillingSummary.mockResolvedValue({
      success: true,
      data: {
        plan: { key: 'pro', name: 'Pro', max_stores: null, max_products: null, max_staff: null },
        subscription_status: 'active',
        current_period_end: '2027-01-01T00:00:00Z',
        has_billing_account: true,
        has_subscription: true,
        cancel_at_period_end: false,
        interval: 'monthly',
      },
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
    expect(mocks.fetchBillingSummary).toHaveBeenCalledTimes(1);
    expect(mocks.dbFindUnique).not.toHaveBeenCalled();
  });

  it('does not import the database client itself', () => {
    const source = readFileSync(join(process.cwd(), 'src/app/dashboard/page.tsx'), 'utf8');

    expect(source).not.toContain('@/lib/db/client');
  });

  it('shows the plan and status read from the billing API', async () => {
    const markup = renderToStaticMarkup((await page()) as React.ReactElement);

    expect(markup).toContain('pro');
    expect(markup).toContain('Active until');
  });

  it('treats an account with no billing organisation as free instead of failing', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({
      success: false,
      error: NO_BILLING_ORGANIZATION_MESSAGE,
    });

    const markup = renderToStaticMarkup((await page()) as React.ReactElement);

    expect(markup).toContain('free');
    expect(markup).not.toContain('Active until');
  });

  it('clears the session when the billing call finds it rejected', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({
      success: false,
      error: 'Invalid authentication',
      status: 401,
    });

    expect(redirectTarget(await rejection(page()))).toBe('/api/auth/clear-session');
  });

  it('does not render an invalid date when the period end is empty', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({
      success: true,
      data: {
        plan: { key: 'pro', name: 'Pro', max_stores: null, max_products: null, max_staff: null },
        subscription_status: 'active',
        current_period_end: null,
        has_billing_account: true,
        has_subscription: true,
        cancel_at_period_end: false,
        interval: 'monthly',
      },
    });

    const markup = renderToStaticMarkup((await page()) as React.ReactElement);

    expect(markup).not.toContain('Invalid Date');
  });

  it.each([
    [{ success: false, error: 'Backend unavailable' }, 'unreachable'],
    [{ success: false, error: 'Request failed', status: 500 }, '500'],
  ])(
    'rethrows when the billing API is down (%o) instead of showing a wrong plan',
    async (failure, detail) => {
      mocks.fetchBillingSummary.mockResolvedValue(failure);

      const error = await rejection(page());

      expect(String(error)).toContain(detail);
      expect(navigationMock.redirect).not.toHaveBeenCalled();
    }
  );

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
