import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/** KAN-250: a failed checkout shows an inline error (no window.alert) and re-enables the button. */

const mocks = vi.hoisted(() => ({ createCheckoutSessionAction: vi.fn() }));
vi.mock('@/app/actions/subscription-actions', () => ({
  createCheckoutSessionAction: mocks.createCheckoutSessionAction,
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { PricingCard } from '@/components/pricing/pricing-card';

const PRO = {
  name: 'Pro',
  price: 15,
  description: 'For professionals',
  features: [],
  limitations: [],
  cta: 'Upgrade',
  href: '/signup',
  popular: true,
};

function renderPro(billingPeriod: 'monthly' | 'yearly' = 'monthly') {
  render(
    <PricingCard
      tier={PRO}
      currencySymbol="$"
      isAuthenticated
      userTier="free"
      billingPeriod={billingPeriod}
    />
  );
  return screen.getByRole('button', { name: /upgrade to pro/i });
}

describe('PricingCard checkout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
  });

  it('shows the action message inline, never window.alert, and re-enables the button', async () => {
    mocks.createCheckoutSessionAction.mockResolvedValue({
      success: false,
      error: 'Create a store first to subscribe.',
      code: 'no_organization',
    });
    const button = renderPro();

    await userEvent.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Create a store first to subscribe.'
    );
    expect(window.alert).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /upgrade to pro/i })).toBeEnabled();
  });

  it('falls back to a generic inline message when the action throws', async () => {
    mocks.createCheckoutSessionAction.mockRejectedValue(new Error('network'));
    const button = renderPro();

    await userEvent.click(button);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not start checkout/i);
    expect(window.alert).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /upgrade to pro/i })).toBeEnabled();
  });

  it('clears the previous error when the user tries again', async () => {
    mocks.createCheckoutSessionAction
      .mockResolvedValueOnce({ success: false, error: 'First failure.' })
      .mockReturnValueOnce(new Promise(() => undefined));
    const button = renderPro();

    await userEvent.click(button);
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: /upgrade to pro/i }));

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it.each(['monthly', 'yearly'] as const)(
    'asks for %s checkout of the pro plan',
    async (period) => {
      mocks.createCheckoutSessionAction.mockReturnValue(new Promise(() => undefined));
      const button = renderPro(period);

      await userEvent.click(button);

      expect(mocks.createCheckoutSessionAction).toHaveBeenCalledWith('pro', period);
    }
  );
});
