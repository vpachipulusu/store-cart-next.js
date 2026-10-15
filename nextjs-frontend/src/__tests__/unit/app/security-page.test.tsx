import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  getTwoFactorStatusAction: vi.fn(),
  getLoginHistoryAction: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/firebase/client', () => ({
  auth: { currentUser: { email: 'a@b.test', providerData: [{ providerId: 'password' }] } },
}));
vi.mock('firebase/auth', () => ({ signOut: vi.fn(), onAuthStateChanged: vi.fn(() => vi.fn()) }));
vi.mock('@/app/actions/user-actions', () => ({
  changePasswordAction: vi.fn(),
  deleteAccountAction: vi.fn(),
  disableTwoFactorAction: vi.fn(),
  getLoginHistoryAction: mocks.getLoginHistoryAction,
  getTwoFactorStatusAction: mocks.getTwoFactorStatusAction,
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

import SecurityPage from '@/app/dashboard/security/page';

describe('SecurityPage two-factor status (KAN-183)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getLoginHistoryAction.mockResolvedValue({ success: true, data: { history: [] } });
  });

  it.each([
    [true, 'Two-factor authentication is enabled'],
    [false, 'Two-factor authentication is not enabled'],
  ])('shows the API status (enabled=%s)', async (enabled, text) => {
    mocks.getTwoFactorStatusAction.mockResolvedValue({ success: true, data: { enabled } });

    render(<SecurityPage />);

    expect(await screen.findByTestId('two-factor-status')).toHaveTextContent(text);
  });

  it('claims nothing when the status cannot be read', async () => {
    mocks.getTwoFactorStatusAction.mockResolvedValue({
      success: false,
      error: 'Failed to get two-factor status',
    });

    render(<SecurityPage />);

    expect(await screen.findByText('Two-factor status unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('two-factor-status')).not.toBeInTheDocument();
  });

  it('offers Disable 2FA only when two-factor is enabled, and never an enrolment button (KAN-180)', async () => {
    mocks.getTwoFactorStatusAction.mockResolvedValue({ success: true, data: { enabled: true } });

    render(<SecurityPage />);

    expect(await screen.findByRole('button', { name: 'Disable 2FA' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /enable 2fa/i })).not.toBeInTheDocument();
  });

  it('shows no 2FA buttons when two-factor is off, but always offers account deletion', async () => {
    mocks.getTwoFactorStatusAction.mockResolvedValue({ success: true, data: { enabled: false } });

    render(<SecurityPage />);

    await screen.findByTestId('two-factor-status');
    expect(screen.queryByRole('button', { name: /2fa/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete Account' })).toBeInTheDocument();
  });
});
