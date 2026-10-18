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
  render(
    <ProvisioningStatus storeId={STORE_ID} storeName="Acme Shop" initialStatus="PROVISIONING" />
  );
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

  it('asks the user to wait when a fresh read shows the store is still being set up', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    await renderStalled();
    const polls = mocks.getStoreStatusAction.mock.calls.length;

    await clickRetry();

    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(polls + 1);
    expect(document.body).toHaveTextContent(/still being set up/i);
    expect(document.body).toHaveTextContent(/15 minutes/i);
  });

  it('shows the store as ready when the fresh read finds it ACTIVE', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    await renderStalled();
    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));

    await clickRetry();

    expect(screen.getByRole('status')).toHaveTextContent(/your store is ready/i);
    expect(document.body).not.toHaveTextContent(/taking longer/i);
    expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveFocus();
  });

  it('shows the failed screen when the fresh read finds it FAILED', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    await renderStalled();
    mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));

    await clickRetry();

    expect(screen.getByRole('status')).toHaveTextContent(/could not finish setting up/i);
    expect(document.body).not.toHaveTextContent(/taking longer/i);
  });

  it('recovers: the retry succeeds and the next poll turns ACTIVE', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: true, data: { attempt: 1 } });
    await renderStalled();
    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));

    await clickRetry();
    await advance(POLL_MAX_MS);

    const link = screen.getByRole('link', { name: /open dashboard/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent(/your store is ready/i);
  });

  it('at the attempt cap hides the button and gives the support reference', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'limit' });
    await renderStalled();

    await clickRetry();

    expect(retryButton()).toBeNull();
    expect(document.body).toHaveTextContent(/maximum number of times/i);
    expect(document.body).toHaveTextContent(STORE_ID);
  });

  it('shows a retryable message when the action rejects', async () => {
    mocks.retryProvisioningAction.mockRejectedValue(new Error('network'));
    await renderStalled();

    await clickRetry();

    expect(document.body).toHaveTextContent(/could not retry the setup/i);
    expect(retryButton()).toBeInTheDocument();
  });

  it('sends one request for a double click', async () => {
    let release: (value: unknown) => void = () => undefined;
    mocks.retryProvisioningAction.mockReturnValue(new Promise((resolve) => (release = resolve)));
    await renderStalled();

    const button = retryButton() as HTMLElement;
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    await act(async () => release({ success: true, data: { attempt: 1 } }));

    expect(mocks.retryProvisioningAction).toHaveBeenCalledTimes(1);
  });

  it('shows who may retry when the caller is not an owner or admin', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'forbidden' });
    await renderStalled();

    await clickRetry();

    expect(document.body).toHaveTextContent(/owner or admin/i);
    expect(retryButton()).toBeNull();
  });

  it('says the check failed when the fresh read itself fails', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    await renderStalled();
    mocks.getStoreStatusAction.mockResolvedValue({ success: false, error: 'x' });

    await clickRetry();

    expect(document.body).toHaveTextContent(/could not retry the setup/i);
  });

  it('Check again clears the stalled state and resumes polling', async () => {
    await renderStalled();
    const polls = mocks.getStoreStatusAction.mock.calls.length;

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /check again/i }));
    });

    expect(retryButton()).toBeNull();
    expect(mocks.getStoreStatusAction.mock.calls.length).toBeGreaterThan(polls);
    expect(screen.getByRole('status')).toHaveTextContent(/we are setting up your store/i);
  });

  it('does not tell a caller who may not retry to press the button', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'forbidden' });
    await renderStalled();

    await clickRetry();

    expect(document.body).not.toHaveTextContent(/use retry setup below/i);
  });
});
