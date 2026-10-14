import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  toast: vi.fn(),
  getUserSettingsAction: vi.fn(),
  getLoginHistoryAction: vi.fn(),
  get2FAStatusAction: vi.fn(),
  getSubscriptionDetailsAction: vi.fn(),
  getPaymentMethodsAction: vi.fn(),
  getSubscriptionInvoicesAction: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn() } }));
vi.mock('@/app/actions/user-actions', () => ({
  getUserSettingsAction: mocks.getUserSettingsAction,
  updateUserSettingsAction: vi.fn(),
  getLoginHistoryAction: mocks.getLoginHistoryAction,
  get2FAStatusAction: mocks.get2FAStatusAction,
  changePasswordAction: vi.fn(),
  deleteAccountAction: vi.fn(),
  exportUserDataAction: vi.fn(),
  initiate2FASetupAction: vi.fn(),
  verify2FASetupAction: vi.fn(),
  disable2FAAction: vi.fn(),
}));
vi.mock('@/app/actions/subscription-actions', () => ({
  getSubscriptionDetailsAction: mocks.getSubscriptionDetailsAction,
  getPaymentMethodsAction: mocks.getPaymentMethodsAction,
  getSubscriptionInvoicesAction: mocks.getSubscriptionInvoicesAction,
  cancelSubscriptionAction: vi.fn(),
  resumeSubscriptionAction: vi.fn(),
  deletePaymentMethodAction: vi.fn(),
  setDefaultPaymentMethodAction: vi.fn(),
  createBillingPortalSessionAction: vi.fn(),
}));

import SettingsPage from '@/app/dashboard/settings/page';
import SecurityPage from '@/app/dashboard/security/page';
import BillingPage from '@/app/dashboard/settings/billing/page';

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.clearAllMocks();
});

describe('SettingsPage initial load', () => {
  it('loads settings once on mount and renders the form', async () => {
    mocks.getUserSettingsAction.mockResolvedValue({
      success: true,
      data: {
        settings: { theme: 'dark', emailNotifications: true, language: 'en', timezone: 'UTC' },
      },
    });

    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(mocks.getUserSettingsAction).toHaveBeenCalledTimes(1);
  });

  it('shows an error toast and leaves the loading state when loading fails', async () => {
    mocks.getUserSettingsAction.mockResolvedValue({ success: false, error: 'nope' });

    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Error', description: 'nope' })
    );
  });
});

describe('SecurityPage initial load', () => {
  it('requests login history once on mount', async () => {
    mocks.getLoginHistoryAction.mockResolvedValue({
      success: true,
      data: { history: [] },
    });

    render(<SecurityPage />);

    await waitFor(() => expect(mocks.getLoginHistoryAction).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('No login history available')).toBeInTheDocument();
  });
});

describe('BillingPage initial load', () => {
  it('fetches billing data once and clears the loading state', async () => {
    mocks.getSubscriptionDetailsAction.mockResolvedValue({
      success: true,
      data: { subscriptionTier: 'free', subscriptionStatus: 'inactive', autoRenewal: false },
    });
    mocks.getPaymentMethodsAction.mockResolvedValue({
      success: true,
      data: { paymentMethods: [] },
    });
    mocks.getSubscriptionInvoicesAction.mockResolvedValue({
      success: true,
      data: { invoices: [] },
    });

    render(<BillingPage />);

    expect(
      await screen.findByRole('heading', { name: 'Billing & Subscription' })
    ).toBeInTheDocument();
    expect(mocks.getSubscriptionDetailsAction).toHaveBeenCalledTimes(1);
  });

  it('shows an error toast and stops loading when the fetch throws', async () => {
    mocks.getSubscriptionDetailsAction.mockRejectedValue(new Error('boom'));
    mocks.getPaymentMethodsAction.mockResolvedValue({
      success: true,
      data: { paymentMethods: [] },
    });
    mocks.getSubscriptionInvoicesAction.mockResolvedValue({
      success: true,
      data: { invoices: [] },
    });
    vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<BillingPage />);

    expect(
      await screen.findByRole('heading', { name: 'Billing & Subscription' })
    ).toBeInTheDocument();
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'Failed to load billing data' })
    );
  });
});
