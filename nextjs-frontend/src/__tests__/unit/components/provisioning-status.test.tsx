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
  POLL_MAX_ATTEMPTS,
  POLL_MAX_FAILURES,
  POLL_MAX_MS,
  RETRY_COOLDOWN_MS,
} from '@/components/onboarding/provisioning-status';

const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';
const ok = (status: string) => ({ success: true, data: { status, name: 'Acme Shop' } });
const failed = { success: false, error: 'Could not check your store. Please try again.' };

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function renderStatus(
  initialStatus: 'PROVISIONING' | 'ACTIVE' | 'SUSPENDED' | 'UNKNOWN' = 'PROVISIONING'
) {
  return render(
    <ProvisioningStatus storeId={STORE_ID} storeName="Acme Shop" initialStatus={initialStatus} />
  );
}

const statusRegion = () => screen.getByRole('status');

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

  it('shows PROVISIONING as setting up and polls on the backoff schedule', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    renderStatus();

    expect(statusRegion()).toHaveTextContent(/we are setting up your store/i);
    expect(screen.queryByRole('link', { name: /open dashboard/i })).toBeNull();
    expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();

    await advance(nextPollDelay(0));
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledWith(STORE_ID);
    expect(statusRegion()).toHaveTextContent(/we are setting up your store/i);

    await advance(nextPollDelay(1) - 1);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(2);
  });

  it('announces ready in the same live region and shows an open-dashboard link, then stops polling', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
    renderStatus();
    const region = statusRegion();
    expect(region).toHaveAttribute('aria-live', 'polite');

    await advance(POLL_INITIAL_MS);
    expect(statusRegion()).toBe(region);
    expect(region).toHaveTextContent(/your store is ready/i);
    expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveAttribute(
      'href',
      '/dashboard'
    );

    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
  });

  it('renders ready immediately when the store is already ACTIVE', () => {
    renderStatus('ACTIVE');
    expect(screen.getByRole('link', { name: /open dashboard/i })).toBeInTheDocument();
    expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();
  });

  it('tolerates transient failures and recovers without showing an error', async () => {
    mocks.getStoreStatusAction
      .mockResolvedValueOnce(failed)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(ok('ACTIVE'));
    renderStatus();

    await advance(POLL_MAX_MS * 4);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(3);
    expect(statusRegion()).toHaveTextContent(/your store is ready/i);
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });

  it('shows an error with a retry only after several consecutive failures', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(failed);
    renderStatus();

    await advance(POLL_MAX_MS * POLL_MAX_FAILURES * 2);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(POLL_MAX_FAILURES);
    expect(statusRegion()).toHaveTextContent(/could not check/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps the retry button out of the live region', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(failed);
    renderStatus();
    await advance(POLL_MAX_MS * POLL_MAX_FAILURES * 2);
    expect(statusRegion()).not.toContainElement(screen.getByRole('button', { name: /try again/i }));
  });

  it('retries immediately and resumes polling', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(failed);
    renderStatus();
    await advance(POLL_MAX_MS * POLL_MAX_FAILURES * 2);

    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
    await act(async () => {
      screen.getByRole('button', { name: /try again/i }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusRegion()).toHaveTextContent(/your store is ready/i);
  });

  it('ignores repeated retry clicks during the cooldown, then allows another', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('SUSPENDED'));
    renderStatus('SUSPENDED');
    const click = async () => {
      await act(async () => {
        screen.getByRole('button', { name: /try again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
    };

    await click();
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /try again/i })).toHaveAttribute(
      'aria-disabled',
      'true'
    );

    await click();
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);

    await advance(RETRY_COOLDOWN_MS);
    expect(screen.getByRole('button', { name: /try again/i })).not.toHaveAttribute(
      'aria-disabled',
      'true'
    );
    await click();
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(2);
  });

  it.each(['SUSPENDED', 'ARCHIVED'])('treats %s as not available with a retry', async (status) => {
    mocks.getStoreStatusAction.mockResolvedValue(ok(status));
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(statusRegion()).toHaveTextContent(/not available/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('says the check failed, not "not available", when the initial status is unknown', () => {
    renderStatus('UNKNOWN');
    expect(statusRegion()).toHaveTextContent(/could not check/i);
    expect(statusRegion()).not.toHaveTextContent(/not available/i);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('stops polling and says the store is not available when it is not found', async () => {
    mocks.getStoreStatusAction.mockResolvedValue({ success: false, notFound: true });
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(statusRegion()).toHaveTextContent(/not available/i);
    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
  });

  it('shows a session-expired message, never the bare word Unauthorized', async () => {
    mocks.getStoreStatusAction.mockResolvedValue({ success: false, code: 'unauthorized' });
    renderStatus();
    await advance(POLL_INITIAL_MS);
    expect(statusRegion()).toHaveTextContent(/session has expired/i);
    expect(statusRegion()).not.toHaveTextContent(/^unauthorized$/i);
  });

  it('stops polling after the attempt cap and offers a retry', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    renderStatus();
    await advance(POLL_MAX_MS * (POLL_MAX_ATTEMPTS + 2));
    expect(statusRegion()).toHaveTextContent(/taking longer/i);
    expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(POLL_MAX_ATTEMPTS);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('clears the pending timer on unmount', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
    const { unmount } = renderStatus();
    unmount();
    await advance(POLL_MAX_MS * 3);
    expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();
  });
  describe('status pill in the live region', () => {
    const pill = () => screen.getByTestId('provisioning-pill');

    it('shows a warn pill while setting up', () => {
      renderStatus('PROVISIONING');
      expect(statusRegion()).toContainElement(pill());
      expect(pill()).toHaveTextContent('Setting up');
      expect(pill().className).toContain('bg-warn');
    });

    it('shows a good pill when ready', () => {
      renderStatus('ACTIVE');
      expect(statusRegion()).toContainElement(pill());
      expect(pill()).toHaveTextContent('Ready');
      expect(pill().className).toContain('bg-good');
    });

    it('shows a crit pill when the store is unavailable', () => {
      renderStatus('SUSPENDED');
      expect(statusRegion()).toContainElement(pill());
      expect(pill()).toHaveTextContent('Needs attention');
      expect(pill().className).toContain('bg-crit');
    });

    it('shows a crit pill when the initial status is unknown', () => {
      renderStatus('UNKNOWN');
      expect(statusRegion()).toContainElement(pill());
      expect(pill()).toHaveTextContent('Needs attention');
      expect(pill().className).toContain('bg-crit');
    });

    it('shows a crit pill after polling gives up', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
      renderStatus();
      await advance(POLL_MAX_MS * (POLL_MAX_ATTEMPTS + 2));
      expect(statusRegion()).toHaveTextContent(/taking longer/i);
      expect(pill()).toHaveTextContent('Needs attention');
      expect(pill().className).toContain('bg-crit');
    });
  });
});
