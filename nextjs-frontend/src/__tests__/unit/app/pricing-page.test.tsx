// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import {
  DB_DOWN,
  REVOKED_SESSION,
  SESSION_CHECK_DOWN,
  navigationMock,
  rejection,
} from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  fetchSessionStatus: vi.fn(),
  fetchBillingSummary: vi.fn(),
  loggerError: vi.fn(),
  loggerWarn: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/api/account', () => ({
  fetchProfile: vi.fn(),
  fetchSessionStatus: mocks.fetchSessionStatus,
}));
vi.mock('@/lib/api/billing', () => ({
  NO_BILLING_ORGANIZATION_MESSAGE: 'No organisation you can manage billing for was found',
  fetchBillingSummary: mocks.fetchBillingSummary,
}));
vi.mock('@/lib/logger', () => ({
  logger: { error: mocks.loggerError, warn: mocks.loggerWarn },
}));
vi.mock('@/config/subscriptions', () => ({
  getSubscriptionPlans: async () => [],
  getCurrencySymbol: async () => '$',
}));
vi.mock('@/components/pricing/pricing-cards-section', () => ({ PricingCardsSection: () => null }));

import PricingPage from '@/app/pricing/page';

/** Finds the PricingCardsSection element's props in the rendered element tree. */
function findCardsProps(node: unknown): Record<string, unknown> | null {
  if (!node || typeof node !== 'object') return null;
  const element = node as ReactElement<Record<string, unknown>>;
  if (element.props && 'isAuthenticated' in element.props) return element.props;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findCardsProps(child);
    if (found) return found;
  }
  return null;
}

describe('PricingPage session check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.fetchSessionStatus.mockResolvedValue({ success: true, data: { uid: 'uid-1' } });
    mocks.fetchBillingSummary.mockResolvedValue({
      success: true,
      data: { plan: { key: 'pro' } },
    });
  });

  it('propagates a redirect thrown while loading the session', async () => {
    const redirectError = Object.assign(new Error('NEXT_REDIRECT'), {
      digest: 'NEXT_REDIRECT;replace;/somewhere;307;',
    });
    mocks.fetchBillingSummary.mockRejectedValue(redirectError);

    expect(await rejection(PricingPage())).toBe(redirectError);
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('shows the logged-out view when the backend reports the session revoked or expired', async () => {
    mocks.fetchSessionStatus.mockResolvedValue(REVOKED_SESSION);

    const props = findCardsProps(await PricingPage());

    expect(props?.isAuthenticated).toBe(false);
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('does not show the logged-out view or end the session when the session check is down', async () => {
    mocks.fetchSessionStatus.mockResolvedValue(SESSION_CHECK_DOWN);

    const error = await rejection(PricingPage());

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe('Session status check failed');
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    expect(mocks.fetchBillingSummary).not.toHaveBeenCalled();
  });

  it('shows the plan the billing API reports for the signed-in user', async () => {
    const props = findCardsProps(await PricingPage());

    expect(props).toMatchObject({ isAuthenticated: true, userTier: 'pro' });
  });

  it('treats a user without a billable organisation as free without a warning', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({
      success: false,
      error: 'No organisation you can manage billing for was found',
    });

    const props = findCardsProps(await PricingPage());

    expect(props).toMatchObject({ isAuthenticated: true, userTier: 'free' });
    expect(mocks.loggerWarn).not.toHaveBeenCalled();
  });

  it('falls back to free and warns when the billing API is unavailable', async () => {
    mocks.fetchBillingSummary.mockResolvedValue({ success: false, error: 'Backend unavailable' });

    const props = findCardsProps(await PricingPage());

    expect(props).toMatchObject({ isAuthenticated: true, userTier: 'free' });
    expect(mocks.loggerWarn).toHaveBeenCalledTimes(1);
  });

  it('logs and rethrows a billing API error instead of showing the logged-out view', async () => {
    mocks.fetchBillingSummary.mockRejectedValue(DB_DOWN);

    expect(await rejection(PricingPage())).toBe(DB_DOWN);
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({
      route: '/pricing',
      errorName: 'Error',
      message: 'connection refused',
      userId: 'uid-1',
    });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });
});
