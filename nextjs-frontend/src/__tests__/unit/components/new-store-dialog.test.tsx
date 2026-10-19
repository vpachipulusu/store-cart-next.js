/**
 * KAN-254: the dashboard "New store" dialog reuses the onboarding store fields and provisioning status, selects
 * the new store once it is ACTIVE, and shows the plan upgrade message when the store limit is reached.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  createAdditionalStoreAction: vi.fn(),
  getStoreStatusAction: vi.fn(),
  retryProvisioningAction: vi.fn(),
  selectStoreAction: vi.fn(),
  refresh: vi.fn(),
  toast: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('@/app/actions/store-actions', () => ({ selectStoreAction: mocks.selectStoreAction }));
vi.mock('@/app/actions/onboarding-actions', () => ({
  createAdditionalStoreAction: mocks.createAdditionalStoreAction,
  getStoreStatusAction: mocks.getStoreStatusAction,
  retryProvisioningAction: mocks.retryProvisioningAction,
}));

import { NewStoreDialog } from '@/components/dashboard/new-store-dialog';
import { SESSION_EXPIRED_MESSAGE } from '@/lib/onboarding/schema';

const NEW_ID = 'pfh0haxfpzowht3oi213cqos';
const LIMIT = 'The Free plan allows 1 store. Upgrade your plan to add more.';
const created = (status: string) => ({
  success: true,
  data: { storeId: NEW_ID, name: 'Second Shop', status },
});

function renderDialog(onOpenChange = vi.fn()) {
  render(<NewStoreDialog open organizationName="Acme Ltd" onOpenChange={onOpenChange} />);
  return onOpenChange;
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/store name/i), 'Second Shop');
  await user.click(screen.getByRole('button', { name: /create store/i }));
}

describe('NewStoreDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.selectStoreAction.mockResolvedValue({ success: true });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('is a dialog named "New store" with the onboarding store fields only', () => {
    renderDialog();
    expect(screen.getByRole('dialog', { name: 'New store' })).toHaveAccessibleDescription(
      /Add another store to Acme Ltd\./
    );
    expect(screen.getByLabelText(/store name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/store address/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/business name/i)).not.toBeInTheDocument();
  });

  it('suggests the address from the name and submits name and address only', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('PROVISIONING'));
    renderDialog();

    await user.type(screen.getByLabelText(/store name/i), 'Second Shop');
    expect(screen.getByLabelText(/store address/i)).toHaveValue('second-shop');
    await user.click(screen.getByRole('button', { name: /create store/i }));

    expect(mocks.createAdditionalStoreAction).toHaveBeenCalledWith({
      storeName: 'Second Shop',
      storeSlug: 'second-shop',
    });
  });

  it('keeps an address the user edited', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('PROVISIONING'));
    renderDialog();

    await user.type(screen.getByLabelText(/store address/i), 'my-shop');
    await fillAndSubmit(user);

    expect(mocks.createAdditionalStoreAction).toHaveBeenCalledWith({
      storeName: 'Second Shop',
      storeSlug: 'my-shop',
    });
  });

  it('shows the provisioning progress while the new store is set up', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('PROVISIONING'));
    renderDialog();

    await fillAndSubmit(user);

    expect(await screen.findByText('We are setting up your store')).toBeInTheDocument();
    expect(screen.queryByLabelText(/store name/i)).not.toBeInTheDocument();
    expect(mocks.selectStoreAction).not.toHaveBeenCalled();
    // Focus moves from the unmounted form to the status, and the dialog copy does not talk about "this page".
    await waitFor(() =>
      expect(
        screen.getByText('We are setting up your store').closest('[role="status"]')
      ).toHaveFocus()
    );
    expect(screen.queryByText(/this page updates/i)).not.toBeInTheDocument();
  });

  it('selects the new store once it is ACTIVE, refreshes, confirms and closes', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('ACTIVE'));
    const onOpenChange = renderDialog();

    await fillAndSubmit(user);

    await waitFor(() => expect(mocks.selectStoreAction).toHaveBeenCalledWith(NEW_ID));
    expect(mocks.selectStoreAction).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Store ready', description: 'Now showing Second Shop.' })
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('keeps the dialog open and toasts when selecting the ready store fails', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('ACTIVE'));
    mocks.selectStoreAction.mockResolvedValue({ success: false, error: 'nope' });
    const onOpenChange = renderDialog();

    await fillAndSubmit(user);

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Could not switch store',
          description: 'nope',
          variant: 'destructive',
        })
      )
    );
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it('toasts when selecting the ready store throws', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('ACTIVE'));
    mocks.selectStoreAction.mockRejectedValue(new Error('network'));
    renderDialog();

    await fillAndSubmit(user);

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Could not switch store', variant: 'destructive' })
      )
    );
  });

  it('keeps the Retry setup path for a store whose setup FAILED', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('FAILED'));
    renderDialog();

    await fillAndSubmit(user);

    expect(await screen.findByRole('button', { name: 'Retry setup' })).toBeInTheDocument();
    expect(mocks.selectStoreAction).not.toHaveBeenCalled();
  });

  it('shows a taken address on the address field and focuses it', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue({
      success: false,
      fieldErrors: { storeSlug: 'That address is already taken. Choose another.' },
    });
    renderDialog();

    await fillAndSubmit(user);

    const address = screen.getByLabelText(/store address/i);
    expect(await screen.findByText('That address is already taken. Choose another.')).toBeVisible();
    expect(address).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(address).toHaveFocus());
    expect(screen.getByRole('button', { name: /create store/i })).not.toHaveAttribute(
      'aria-disabled',
      'true'
    );
  });

  it('shows the plan upgrade message instead of the form when the store limit is reached', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue({
      success: false,
      limitReached: true,
      error: LIMIT,
    });
    renderDialog();

    await fillAndSubmit(user);

    const upgrade = await screen.findByTestId('store-limit');
    expect(upgrade).toHaveAttribute('role', 'status');
    expect(upgrade).toHaveTextContent(LIMIT);
    expect(screen.getByRole('link', { name: /see plans/i })).toHaveAttribute('href', '/pricing');
    expect(screen.queryByLabelText(/store name/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await waitFor(() => expect(upgrade).toHaveFocus());
  });

  it('shows the session-expired text for the unauthorized code', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue({ success: false, code: 'unauthorized' });
    renderDialog();

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
  });

  it('shows a form error from the action', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue({
      success: false,
      error: 'Only an owner or admin of this business can add a store.',
    });
    renderDialog();

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('Only an owner or admin');
  });

  it('shows the generic error when the action throws', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockRejectedValue(new Error('network'));
    renderDialog();

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'We could not set up your store. Please try again.'
    );
  });

  it('submits once while a request is in flight', async () => {
    const user = userEvent.setup();
    let finish: (value: unknown) => void = () => {};
    mocks.createAdditionalStoreAction.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderDialog();

    await fillAndSubmit(user);
    const button = screen.getByRole('button', { name: /creating/i });
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await user.click(button);

    expect(mocks.createAdditionalStoreAction).toHaveBeenCalledTimes(1);
    finish(created('PROVISIONING'));
    expect(await screen.findByText('We are setting up your store')).toBeInTheDocument();
  });

  it('offers to switch again when selecting the ready store failed, and closes once it works', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('ACTIVE'));
    mocks.selectStoreAction
      .mockResolvedValueOnce({ success: false, error: 'nope' })
      .mockResolvedValueOnce({ success: true });
    const onOpenChange = renderDialog();

    await fillAndSubmit(user);
    await user.click(await screen.findByRole('button', { name: 'Switch to Second Shop' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.selectStoreAction).toHaveBeenCalledTimes(2);
  });

  it('polls a PROVISIONING store and selects it once when it turns ACTIVE', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mocks.createAdditionalStoreAction.mockResolvedValue(created('PROVISIONING'));
    mocks.getStoreStatusAction.mockResolvedValue({
      success: true,
      data: { status: 'ACTIVE', name: 'Second Shop' },
    });
    const onOpenChange = renderDialog();

    await fillAndSubmit(user);
    await screen.findByText('We are setting up your store');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.getStoreStatusAction).toHaveBeenCalledWith(NEW_ID);
    expect(mocks.selectStoreAction).toHaveBeenCalledTimes(1);
    expect(mocks.selectStoreAction).toHaveBeenCalledWith(NEW_ID);
  });

  it('selects the store once after Retry setup turns a FAILED store ACTIVE', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction.mockResolvedValue(created('FAILED'));
    mocks.retryProvisioningAction.mockResolvedValue({ success: true, data: { attempt: 2 } });
    mocks.getStoreStatusAction.mockResolvedValue({
      success: true,
      data: { status: 'ACTIVE', name: 'Second Shop' },
    });
    const onOpenChange = renderDialog();

    await fillAndSubmit(user);
    await user.click(await screen.findByRole('button', { name: 'Retry setup' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.retryProvisioningAction).toHaveBeenCalledWith(NEW_ID);
    expect(mocks.selectStoreAction).toHaveBeenCalledTimes(1);
  });

  it('re-enables the button after a failed submit so the user can submit again', async () => {
    const user = userEvent.setup();
    mocks.createAdditionalStoreAction
      .mockResolvedValueOnce({ success: false, error: 'Try again' })
      .mockResolvedValueOnce(created('PROVISIONING'));
    renderDialog();

    await fillAndSubmit(user);
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: /create store/i }));

    expect(await screen.findByText('We are setting up your store')).toBeInTheDocument();
    expect(mocks.createAdditionalStoreAction).toHaveBeenCalledTimes(2);
  });

  it('renders nothing when closed', () => {
    render(<NewStoreDialog open={false} organizationName="Acme Ltd" onOpenChange={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
