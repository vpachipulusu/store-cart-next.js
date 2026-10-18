/** KAN-248: a store that never leaves PROVISIONING gets a plain message and a working "Retry setup". */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  getStoreStatusAction: vi.fn(),
  retryProvisioningAction: vi.fn(),
}));
vi.mock('@/app/actions/onboarding-actions', () => ({
  getStoreStatusAction: mocks.getStoreStatusAction,
  retryProvisioningAction: mocks.retryProvisioningAction,
}));

import {
  ProvisioningStatus,
  POLL_MAX_ATTEMPTS,
  POLL_MAX_MS,
} from '@/components/onboarding/provisioning-status';

const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';
const ok = (status: string) => ({ success: true, data: { status, name: 'Acme Shop' } });

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function renderStalled() {
  mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
  render(<ProvisioningStatus storeId={STORE_ID} storeName="Acme Shop" initialStatus="PROVISIONING" />);
  await advance(POLL_MAX_MS * (POLL_MAX_ATTEMPTS + 2));
}

const retryButton = () => screen.queryByRole('button', { name: /retry setup/i });

async function clickRetry() {
  await act(async () => {
    fireEvent.click(retryButton() as HTMLElement);
  });
}

describe('stalled provisioning', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('says setup is taking longer and offers Retry setup, with no technical detail', async () => {
    await renderStalled();

    expect(screen.getByRole('status')).toHaveTextContent(/taking longer than expected/i);
    expect(retryButton()).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/qstash|neon|signature|vercel/i);
  });

  it('re-runs setup and goes back to the setting-up progress', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: true, data: { attempt: 1 } });
    await renderStalled();

    await clickRetry();

    expect(mocks.retryProvisioningAction).toHaveBeenCalledWith(STORE_ID);
    expect(screen.getByRole('status')).toHaveTextContent(/we are setting up your store/i);
  });

  it('asks the user to wait when the store is not stuck long enough to retry yet', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    await renderStalled();
    const polls = mocks.getStoreStatusAction.mock.calls.length;

    await clickRetry();

    expect(document.body).toHaveTextContent(/still being set up/i);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(polls);
  });

  it('shows who may retry when the caller is not an owner or admin', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'forbidden' });
    await renderStalled();

    await clickRetry();

    expect(document.body).toHaveTextContent(/owner or admin/i);
    expect(retryButton()).toBeNull();
  });
});
