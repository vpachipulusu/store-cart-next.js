import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  getTwoFactorStatusAction: vi.fn(),
  getLoginHistoryAction: vi.fn(),
}));

vi.mock('@/app/actions/user-actions', () => ({
  changePasswordAction: vi.fn(),
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
});
