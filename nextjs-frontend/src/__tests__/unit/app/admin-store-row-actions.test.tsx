import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  suspendStoreAction: vi.fn(),
  unsuspendStoreAction: vi.fn(),
  migrateStoreAction: vi.fn(),
  refresh: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('@/app/actions/admin-store-actions', () => ({
  suspendStoreAction: mocks.suspendStoreAction,
  unsuspendStoreAction: mocks.unsuspendStoreAction,
  migrateStoreAction: mocks.migrateStoreAction,
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));

import { StoreRowActions } from '@/app/(admin)/admin/stores/store-row-actions';

const GENERIC = 'Something went wrong. Please try again.';

function renderActions(status: Parameters<typeof StoreRowActions>[0]['status']) {
  return render(<StoreRowActions storeId="store-1" storeName="Acme Shop" status={status} />);
}

describe('StoreRowActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('offers migrations and suspend for an active store', () => {
    renderActions('ACTIVE');

    expect(
      screen.getByRole('button', { name: 'Run migrations for Acme Shop' })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Suspend Acme Shop' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^unsuspend/i })).not.toBeInTheDocument();
  });

  it('offers migrations and unsuspend for a suspended store', () => {
    renderActions('SUSPENDED');

    expect(
      screen.getByRole('button', { name: 'Run migrations for Acme Shop' })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unsuspend Acme Shop' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^suspend/i })).not.toBeInTheDocument();
  });

  it.each(['PROVISIONING', 'ARCHIVED'] as const)('offers nothing for a %s store', (status) => {
    renderActions(status);

    expect(screen.getByText('No actions')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not suspend when the confirmation is cancelled', async () => {
    const user = userEvent.setup();
    renderActions('ACTIVE');

    await user.click(screen.getByRole('button', { name: 'Suspend Acme Shop' }));
    expect(await screen.findByText(/storefront goes offline/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mocks.suspendStoreAction).not.toHaveBeenCalled();
  });

  it('suspends after confirmation, toasts the message and refreshes', async () => {
    mocks.suspendStoreAction.mockResolvedValue({
      success: true,
      data: { message: 'Store suspended' },
    });
    const user = userEvent.setup();
    renderActions('ACTIVE');

    await user.click(screen.getByRole('button', { name: 'Suspend Acme Shop' }));
    await user.click(await screen.findByRole('button', { name: 'Suspend store' }));

    await waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
    expect(mocks.suspendStoreAction).toHaveBeenCalledWith('store-1');
    expect(mocks.toast).toHaveBeenCalledWith({ title: 'Success', description: 'Store suspended' });
  });

  it('unsuspends and runs migrations through their actions', async () => {
    mocks.unsuspendStoreAction.mockResolvedValue({
      success: true,
      data: { message: 'Store unsuspended' },
    });
    mocks.migrateStoreAction.mockResolvedValue({
      success: true,
      data: { message: 'Schema migrated' },
    });
    const user = userEvent.setup();
    renderActions('SUSPENDED');

    await user.click(screen.getByRole('button', { name: 'Unsuspend Acme Shop' }));
    await waitFor(() => expect(mocks.unsuspendStoreAction).toHaveBeenCalledWith('store-1'));
    await user.click(screen.getByRole('button', { name: 'Run migrations for Acme Shop' }));
    await waitFor(() => expect(mocks.migrateStoreAction).toHaveBeenCalledWith('store-1'));
  });

  it('toasts the curated error and still refreshes when the action fails', async () => {
    mocks.migrateStoreAction.mockResolvedValue({
      success: false,
      error: 'The store is not in a state that allows this.',
    });
    const user = userEvent.setup();
    renderActions('ACTIVE');

    await user.click(screen.getByRole('button', { name: 'Run migrations for Acme Shop' }));

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith({
        title: 'Error',
        description: 'The store is not in a state that allows this.',
        variant: 'destructive',
      })
    );
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it('falls back to a generic message when the failure has no text', async () => {
    mocks.migrateStoreAction.mockResolvedValue({ success: false });
    const user = userEvent.setup();
    renderActions('ACTIVE');

    await user.click(screen.getByRole('button', { name: 'Run migrations for Acme Shop' }));

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        expect.objectContaining({ description: GENERIC, variant: 'destructive' })
      )
    );
  });

  it('shows a generic error when the action throws', async () => {
    mocks.migrateStoreAction.mockRejectedValue(new Error('SECRET network detail'));
    const user = userEvent.setup();
    renderActions('ACTIVE');

    await user.click(screen.getByRole('button', { name: 'Run migrations for Acme Shop' }));

    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith({
        title: 'Error',
        description: GENERIC,
        variant: 'destructive',
      })
    );
    expect(JSON.stringify(mocks.toast.mock.calls)).not.toContain('SECRET');
  });
});
