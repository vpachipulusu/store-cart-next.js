import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  getConnectStatusAction: vi.fn(),
  startConnectOnboardingAction: vi.fn(),
}));

vi.mock('@/app/actions/connect-actions', () => ({
  getConnectStatusAction: mocks.getConnectStatusAction,
  startConnectOnboardingAction: mocks.startConnectOnboardingAction,
}));

import { ConnectPaymentsPanel } from '@/components/dashboard/settings/connect-payments-panel';

function status(overrides: Record<string, boolean> = {}) {
  return {
    success: true,
    data: {
      hasAccount: false,
      chargesEnabled: false,
      payoutsEnabled: false,
      detailsSubmitted: false,
      ...overrides,
    },
  };
}

const assign = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('location', { ...window.location, search: '', assign });
  mocks.getConnectStatusAction.mockResolvedValue(status());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ConnectPaymentsPanel', () => {
  it('announces loading, then shows a not-set-up account with a Start button', async () => {
    render(<ConnectPaymentsPanel />);

    expect(screen.getByRole('status')).toHaveTextContent(/loading payment status/i);
    expect(await screen.findByRole('heading', { level: 2, name: 'Payments' })).toBeInTheDocument();
    expect(screen.getByText('Not set up')).toBeInTheDocument();
    expect(screen.getAllByText('Not enabled')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Start onboarding' })).toBeEnabled();
    expect(screen.getByText(/checkout stays off/i)).toBeInTheDocument();
  });

  it('offers Continue once an account exists but charges are not enabled', async () => {
    mocks.getConnectStatusAction.mockResolvedValue(status({ hasAccount: true }));

    render(<ConnectPaymentsPanel />);

    expect(await screen.findByRole('button', { name: 'Continue onboarding' })).toBeInTheDocument();
    expect(screen.getByText('Created')).toBeInTheDocument();
  });

  it('hides the button when everything is enabled', async () => {
    mocks.getConnectStatusAction.mockResolvedValue(
      status({
        hasAccount: true,
        chargesEnabled: true,
        payoutsEnabled: true,
        detailsSubmitted: true,
      })
    );

    render(<ConnectPaymentsPanel />);

    expect(await screen.findByText('Submitted')).toBeInTheDocument();
    expect(screen.getAllByText('Enabled')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /onboarding/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/checkout stays off/i)).not.toBeInTheDocument();
  });

  it('shows an alert with a working retry when the status cannot be loaded', async () => {
    mocks.getConnectStatusAction.mockResolvedValueOnce({ success: false, error: 'down' });
    const user = userEvent.setup();

    render(<ConnectPaymentsPanel />);

    expect(await screen.findByRole('alert')).toHaveTextContent('down');
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('button', { name: 'Start onboarding' })).toBeInTheDocument();
  });

  it('shows the failure state when the action throws', async () => {
    mocks.getConnectStatusAction.mockRejectedValueOnce(new Error('x'));

    render(<ConnectPaymentsPanel />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not load your payment status/i
    );
  });

  it('redirects to the Stripe-hosted link and disables the button while starting', async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.startConnectOnboardingAction.mockReturnValue(new Promise((r) => (resolve = r)));
    const user = userEvent.setup();
    render(<ConnectPaymentsPanel />);

    await user.click(await screen.findByRole('button', { name: 'Start onboarding' }));

    expect(screen.getByRole('button', { name: 'Start onboarding' })).toBeDisabled();
    resolve({ success: true, data: { url: 'https://connect.stripe.com/setup/abc' } });
    await vi.waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://connect.stripe.com/setup/abc')
    );
  });

  it('stays disabled after a successful redirect so a second link cannot be created', async () => {
    mocks.startConnectOnboardingAction.mockResolvedValue({
      success: true,
      data: { url: 'https://connect.stripe.com/setup/abc' },
    });
    const user = userEvent.setup();
    render(<ConnectPaymentsPanel />);

    await user.click(await screen.findByRole('button', { name: 'Start onboarding' }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: 'Start onboarding' })).toBeDisabled();
  });

  it('shows the action error and does not navigate when starting fails', async () => {
    mocks.startConnectOnboardingAction.mockResolvedValue({
      success: false,
      error: 'We could not reach the payment provider. Please try again in a few minutes.',
    });
    const user = userEvent.setup();
    render(<ConnectPaymentsPanel />);

    await user.click(await screen.findByRole('button', { name: 'Start onboarding' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/payment provider/i);
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Start onboarding' })).toBeEnabled();
  });

  it.each([
    'javascript:alert(1)',
    'http://connect.stripe.com/x',
    'https://evil.example/x',
    'not a url',
  ])('refuses to navigate to %s', async (url) => {
    mocks.startConnectOnboardingAction.mockResolvedValue({ success: true, data: { url } });
    const user = userEvent.setup();
    render(<ConnectPaymentsPanel />);

    await user.click(await screen.findByRole('button', { name: 'Start onboarding' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not start payment setup/i);
    expect(assign).not.toHaveBeenCalled();
  });

  it('shows an error when the start action throws', async () => {
    mocks.startConnectOnboardingAction.mockRejectedValue(new Error('x'));
    const user = userEvent.setup();
    render(<ConnectPaymentsPanel />);

    await user.click(await screen.findByRole('button', { name: 'Start onboarding' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not start payment setup/i);
  });

  it.each([
    ['?connect=return', /may take a moment to confirm/i],
    ['?connect=refresh', /setup link expired/i],
  ])('explains the return marker %s', async (search, message) => {
    vi.stubGlobal('location', { ...window.location, search, assign });

    render(<ConnectPaymentsPanel />);

    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it('ignores unknown return markers', async () => {
    vi.stubGlobal('location', { ...window.location, search: '?connect=evil', assign });

    render(<ConnectPaymentsPanel />);

    await screen.findByRole('button', { name: 'Start onboarding' });
    expect(screen.queryByText(/may take a moment|link expired/i)).not.toBeInTheDocument();
  });
});
