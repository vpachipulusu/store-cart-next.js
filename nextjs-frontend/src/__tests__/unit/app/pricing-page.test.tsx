// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { DB_DOWN, SESSION_EXPIRED, navigationMock, rejection } from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  userFindUnique: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/db/client', () => ({ db: { user: { findUnique: mocks.userFindUnique } } }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
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
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1' });
    mocks.userFindUnique.mockResolvedValue({ id: 'u1', subscriptionTier: 'pro' });
  });

  it('propagates a redirect thrown while loading the session', async () => {
    const redirectError = Object.assign(new Error('NEXT_REDIRECT'), {
      digest: 'NEXT_REDIRECT;replace;/somewhere;307;',
    });
    mocks.userFindUnique.mockRejectedValue(redirectError);

    expect(await rejection(PricingPage())).toBe(redirectError);
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('shows the logged-out view when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const props = findCardsProps(await PricingPage());

    expect(props?.isAuthenticated).toBe(false);
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('logs and rethrows a database error instead of showing the logged-out view', async () => {
    mocks.userFindUnique.mockRejectedValue(DB_DOWN);

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
