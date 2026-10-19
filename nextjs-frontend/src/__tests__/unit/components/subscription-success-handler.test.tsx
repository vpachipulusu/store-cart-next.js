import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';

/**
 * KAN-251: when the plan has not flipped after the poll window, the dashboard keeps telling the user their payment
 * went through (it used to strip ?upgrade=success after a second, so the banner vanished and nothing was explained).
 */

const mocks = vi.hoisted(() => {
  const replace = vi.fn();
  const refresh = vi.fn();
  return {
    replace,
    refresh,
    router: { replace, refresh },
    searchParams: new URLSearchParams('upgrade=success'),
    getSubscriptionStatusAction: vi.fn(),
    verifyUpgradeSessionAction: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => mocks.router,
  useSearchParams: () => mocks.searchParams,
}));
vi.mock('@/app/actions/subscription-actions', () => ({
  getSubscriptionStatusAction: mocks.getSubscriptionStatusAction,
  verifyUpgradeSessionAction: mocks.verifyUpgradeSessionAction,
}));

import { SubscriptionSuccessHandler } from '@/components/dashboard/subscription-success-handler';

const FREE = { success: true, data: { subscriptionTier: 'free', subscriptionStatus: 'inactive' } };
const PRO = { success: true, data: { subscriptionTier: 'pro', subscriptionStatus: 'active' } };

async function renderAndAdvance(ms: number) {
  render(<SubscriptionSuccessHandler />);
  // Let verification and the first status check settle before moving the clock, or timers registered by them
  // would be scheduled after the whole advance has already elapsed.
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('SubscriptionSuccessHandler', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    vi.clearAllMocks();
    mocks.verifyUpgradeSessionAction.mockResolvedValue({ success: true, data: { valid: true } });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('tells the user the payment was received and keeps the banner when the plan never flips', async () => {
    mocks.getSubscriptionStatusAction.mockResolvedValue(FREE);

    await renderAndAdvance(40_000);

    expect(screen.getByText(/payment received/i)).toBeInTheDocument();
    expect(screen.getByText(/contact support/i)).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalledWith('/dashboard');
  });

  it('shows the processing state while it is still polling', async () => {
    mocks.getSubscriptionStatusAction.mockResolvedValue(FREE);

    await renderAndAdvance(3_000);

    expect(screen.getByText(/processing your subscription/i)).toBeInTheDocument();
  });

  it('activates and refreshes the dashboard once the plan is Pro', async () => {
    mocks.getSubscriptionStatusAction.mockResolvedValue(PRO);

    await renderAndAdvance(5_000);

    expect(screen.getByText(/subscription activated/i)).toBeInTheDocument();
    expect(mocks.replace).toHaveBeenCalledWith('/dashboard');
  });

  it('removes a forged ?upgrade=success straight away', async () => {
    mocks.verifyUpgradeSessionAction.mockResolvedValue({
      success: true,
      data: { valid: false, reason: 'No valid checkout session found' },
    });

    await renderAndAdvance(100);

    expect(mocks.replace).toHaveBeenCalledWith('/dashboard');
    expect(mocks.getSubscriptionStatusAction).not.toHaveBeenCalled();
  });
});
