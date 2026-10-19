import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  retryProvisioningAction: vi.fn(),
  push: vi.fn(),
}));

vi.mock('@/app/actions/onboarding-actions', () => ({
  retryProvisioningAction: mocks.retryProvisioningAction,
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));

import { StoreSetupState } from '@/components/dashboard/store-setup-state';

const STATUS_PAGE = '/dashboard/onboarding/status/store-1';

function renderState(status: 'PROVISIONING' | 'FAILED') {
  return render(<StoreSetupState storeId="store-1" storeName="Acme Shop" status={status} />);
}

describe('StoreSetupState (KAN-255)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('says a PROVISIONING store is still being set up, not that data could not be reached', () => {
    renderState('PROVISIONING');

    expect(
      screen.getByRole('heading', { name: 'Acme Shop is still being set up' })
    ).toBeInTheDocument();
    expect(screen.queryByText(/could not be reached/i)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View setup progress' })).toHaveAttribute(
      'href',
      STATUS_PAGE
    );
    expect(screen.getByRole('button', { name: 'Retry setup' })).toBeInTheDocument();
  });

  it('says setup failed for a FAILED store and offers a retry', () => {
    renderState('FAILED');

    expect(
      screen.getByRole('heading', { name: 'Setting up Acme Shop failed' })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry setup' })).toBeInTheDocument();
  });

  it('re-runs setup and opens the progress page on success', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: true, data: { attempt: 1 } });
    const user = userEvent.setup();
    renderState('FAILED');

    await user.click(screen.getByRole('button', { name: 'Retry setup' }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(STATUS_PAGE));
    expect(mocks.retryProvisioningAction).toHaveBeenCalledWith('store-1');
  });

  it('asks to wait when the backend says setup is still running (not stuck yet)', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    const user = userEvent.setup();
    renderState('PROVISIONING');

    await user.click(screen.getByRole('button', { name: 'Retry setup' }));

    expect(await screen.findByRole('status')).toHaveTextContent(/still being set up.*15 minutes/i);
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it.each([
    [{ success: false, reason: 'limit' }, /maximum number of times.*contact support/i],
    [{ success: false, reason: 'forbidden' }, /only an owner or admin/i],
    [{ success: false, reason: 'rate_limited' }, /too many attempts/i],
    [{ success: false, code: 'unauthorized' }, /session has expired/i],
    [{ success: false, reason: 'unavailable' }, /could not retry the setup/i],
  ])('explains a failed retry (%o)', async (result, message) => {
    mocks.retryProvisioningAction.mockResolvedValue(result);
    const user = userEvent.setup();
    renderState('FAILED');

    await user.click(screen.getByRole('button', { name: 'Retry setup' }));

    expect(await screen.findByRole('status')).toHaveTextContent(message);
  });

  it('shows a generic retry error when the action throws', async () => {
    mocks.retryProvisioningAction.mockRejectedValue(new Error('network'));
    const user = userEvent.setup();
    renderState('FAILED');

    await user.click(screen.getByRole('button', { name: 'Retry setup' }));

    expect(await screen.findByRole('status')).toHaveTextContent(/could not retry the setup/i);
  });

  it('disables the button while the retry runs, so it cannot be sent twice', async () => {
    let finish: (value: { success: boolean; reason: string }) => void = () => {};
    mocks.retryProvisioningAction.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    renderState('FAILED');

    const button = screen.getByRole('button', { name: 'Retry setup' });
    await user.click(button);
    await user.click(button);

    expect(button).toBeDisabled();
    expect(mocks.retryProvisioningAction).toHaveBeenCalledTimes(1);
    finish({ success: false, reason: 'unavailable' });
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
