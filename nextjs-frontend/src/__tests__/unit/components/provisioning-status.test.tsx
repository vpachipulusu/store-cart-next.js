/** KAN-60: the status screen polls the store, shows PROVISIONING as setting up and ACTIVE as ready. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({ getStoreStatusAction: vi.fn() }));
vi.mock('@/app/actions/onboarding-actions', () => ({
  getStoreStatusAction: mocks.getStoreStatusAction,
}));

import {
  nextPollDelay,
  ProvisioningStatus,
  POLL_INITIAL_MS,
  POLL_MAX_MS,
  POLL_MAX_ATTEMPTS,
} from '@/components/onboarding/provisioning-status';

const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';
const ok = (status: string) => ({ success: true, data: { status, name: 'Acme Shop' } });

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function renderStatus(initialStatus = 'PROVISIONING') {
  return render(
    <ProvisioningStatus storeId={STORE_ID} storeName="Acme Shop" initialStatus={initialStatus} />
  );
}

describe('nextPollDelay', () => {
  it('backs off from the initial delay up to the cap', () => {
    expect(nextPollDelay(0)).toBe(POLL_INITIAL_MS);
    expect(nextPollDelay(1)).toBeGreaterThan(nextPollDelay(0));
    expect(nextPollDelay(50)).toBe(POLL_MAX_MS);
  });
});

describe('ProvisioningStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('shows PROVISIONING as setting up and keeps polling', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    renderStatus();

    expect(screen.getByRole('status')).toHaveTextContent(/setting up/i);
    expect(screen.queryByRole('link', { name: /open dashboard/i })).toBeNull();

    await advance(POLL_INITIAL_MS);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledWith(STORE_ID);
    expect(screen.getByRole('status')).toHaveTextContent(/setting up/i);

    await advance(POLL_MAX_MS);
    expect(mocks.getStoreStatusAction.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('shows ready with an open-dashboard link once the store becomes ACTIVE, and stops polling', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
    renderStatus();

    await advance(POLL_INITIAL_MS);
    expect(screen.getByRole('status')).toHaveTextContent(/ready/i);
    expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveAttribute(
      'href',
      '/dashboard'
    );

    const calls = mocks.getStoreStatusAction.mock.calls.length;
    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction.mock.calls.length).toBe(calls);
  });

  it('renders ready immediately when the store is already ACTIVE', () => {
    renderStatus('ACTIVE');
    expect(screen.getByRole('link', { name: /open dashboard/i })).toBeInTheDocument();
    expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();
  });

  it('offers a retry when a status check fails, and polling resumes after it', async () => {
    mocks.getStoreStatusAction.mockResolvedValueOnce({ success: false, error: 'Could not check' });
    renderStatus();

    await advance(POLL_INITIAL_MS);
    expect(screen.getByRole('alert')).toHaveTextContent(/could not check/i);
    const retry = screen.getByRole('button', { name: /try again/i });

    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
    await act(async () => {
      retry.click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole('status')).toHaveTextContent(/ready/i);
  });

  it.each(['SUSPENDED', 'ARCHIVED', 'WHATEVER'])(
    'treats an unexpected status %s as unavailable with a retry',
    async (status) => {
      mocks.getStoreStatusAction.mockResolvedValue(ok(status));
      renderStatus();
      await advance(POLL_INITIAL_MS);
      expect(screen.getByRole('alert')).toHaveTextContent(/not available/i);
      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    }
  );

  it('stops polling and shows an error when the store is not found', async () => {
    mocks.getStoreStatusAction.mockResolvedValue({ success: false, error: 'x', notFound: true });
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(screen.getByRole('alert')).toHaveTextContent(/not available/i);
    const calls = mocks.getStoreStatusAction.mock.calls.length;
    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction.mock.calls.length).toBe(calls);
  });

  it('clears the pending timer on unmount', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    const { unmount } = renderStatus();
    unmount();
    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();
  });

  it('offers a retry when the status action itself rejects', async () => {
    mocks.getStoreStatusAction.mockRejectedValue(new Error('network'));
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(screen.getByRole('alert')).toHaveTextContent(/could not check/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('shows a session-expired message instead of the raw Unauthorized', async () => {
    mocks.getStoreStatusAction.mockResolvedValue({ success: false, error: 'Unauthorized' });
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(screen.getByRole('alert')).toHaveTextContent(/session has expired/i);
  });

  it('stops polling after the attempt cap and offers a retry', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    renderStatus();
    await advance(POLL_MAX_MS * (POLL_MAX_ATTEMPTS + 2));
    expect(screen.getByRole('alert')).toHaveTextContent(/taking longer/i);
    expect(mocks.getStoreStatusAction.mock.calls.length).toBe(POLL_MAX_ATTEMPTS);
  });
});
