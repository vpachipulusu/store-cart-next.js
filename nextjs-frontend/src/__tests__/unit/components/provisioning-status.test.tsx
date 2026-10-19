/** KAN-60: the status screen polls the store, shows PROVISIONING as setting up and ACTIVE as ready. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  getStoreStatusAction: vi.fn(),
  retryProvisioningAction: vi.fn(),
}));
vi.mock('@/app/actions/onboarding-actions', () => ({
  getStoreStatusAction: mocks.getStoreStatusAction,
  retryProvisioningAction: mocks.retryProvisioningAction,
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
  initialStatus: 'PROVISIONING' | 'ACTIVE' | 'FAILED' | 'SUSPENDED' | 'UNKNOWN' = 'PROVISIONING'
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
    expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
  });

  describe('FAILED provisioning (KAN-191)', () => {
    it('explains that setup did not finish, with no claim that a re-run was started', async () => {
      renderStatus('FAILED');
      expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
      const screenText = screen.getByTestId('store-status');
      expect(screenText).toHaveTextContent(/Acme Shop/);
      expect(screenText).toHaveTextContent(/contact support/i);
      expect(screenText).toHaveTextContent(STORE_ID);
      // The support details are not re-read on every status change.
      expect(statusRegion()).not.toHaveTextContent(/contact support/i);
      expect(statusRegion()).not.toHaveTextContent(STORE_ID);
      expect(statusRegion()).not.toHaveTextContent(/not available/i);
      expect(screen.getByTestId('provisioning-pill')).toHaveTextContent('Needs attention');
      expect(screen.queryByRole('link', { name: /open dashboard/i })).toBeNull();
      await advance(POLL_MAX_MS * 3);
      expect(mocks.getStoreStatusAction).not.toHaveBeenCalled();
    });

    it('labels the button as a status check, not a re-run, and keeps it out of the live region', () => {
      renderStatus('FAILED');
      const button = screen.getByRole('button', { name: /check again/i });
      expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
      expect(statusRegion()).not.toContainElement(button);
    });

    it('shows the failed copy when polling discovers FAILED, and stops polling', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('PROVISIONING');
      await advance(POLL_INITIAL_MS);
      expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
      await advance(POLL_MAX_MS * 3);
      expect(mocks.getStoreStatusAction).toHaveBeenCalledTimes(1);
    });

    it('re-reads the status on "Check again" and shows the ready screen if the store became ACTIVE', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
      renderStatus('FAILED');
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(mocks.getStoreStatusAction).toHaveBeenCalledWith(STORE_ID);
      expect(statusRegion()).toHaveTextContent(/your store is ready/i);
      expect(screen.getByRole('link', { name: /open dashboard/i })).toBeInTheDocument();
    });

    it('moves focus to the dashboard link when a check turns the store ACTIVE', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
      renderStatus('FAILED');
      const button = screen.getByRole('button', { name: /check again/i });
      button.focus();
      await act(async () => {
        button.click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole('link', { name: /open dashboard/i })).toHaveFocus();
    });

    it('keeps showing the failed copy when the check still reports FAILED', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('FAILED');
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
      expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
    });

    it('tells the user in the live region when a check finds the store still FAILED', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('FAILED');
      expect(statusRegion()).not.toHaveTextContent(/still not finished/i);
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(statusRegion()).toHaveTextContent(/still not finished/i);
    });

    it('announces every repeat check: the line clears and shows again on the second check', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('FAILED');
      const check = async () => {
        await act(async () => {
          screen.getByRole('button', { name: /check again/i }).click();
          await vi.advanceTimersByTimeAsync(0);
        });
      };
      await check();
      const first = screen.getByText(/still not finished/i);
      await advance(RETRY_COOLDOWN_MS);

      mocks.getStoreStatusAction.mockImplementationOnce(() => new Promise(() => {}));
      await check();
      expect(screen.queryByText(/still not finished/i)).toBeNull();

      await advance(RETRY_COOLDOWN_MS);
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      await check();
      const second = screen.getByText(/still not finished/i);
      expect(second).toBeInTheDocument();
      expect(second).not.toBe(first);
    });

    it('does not say "still" when the store was not FAILED before the check', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('SUSPENDED');
      await act(async () => {
        screen.getByRole('button', { name: /try again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
      expect(statusRegion()).not.toHaveTextContent(/still not finished/i);
    });

    it('drops the "still not finished" line when a later check itself fails', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
      renderStatus('FAILED');
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(statusRegion()).toHaveTextContent(/still not finished/i);
      await advance(RETRY_COOLDOWN_MS);

      mocks.getStoreStatusAction.mockResolvedValue(failed);
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(POLL_MAX_MS * POLL_MAX_FAILURES * 2);
      });
      expect(statusRegion()).toHaveTextContent(/could not check/i);
      expect(statusRegion()).not.toHaveTextContent(/still not finished/i);
    });

    it('keeps the failed explanation and adds the problem when the check itself keeps failing', async () => {
      mocks.getStoreStatusAction.mockResolvedValue(failed);
      renderStatus('FAILED');
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(POLL_MAX_MS * POLL_MAX_FAILURES * 2);
      });
      expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
      expect(statusRegion()).toHaveTextContent(/could not check/i);
      expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
    });

    it('resumes polling when a check finds the store PROVISIONING again, then shows ready', async () => {
      mocks.getStoreStatusAction
        .mockResolvedValueOnce(ok('PROVISIONING'))
        .mockResolvedValue(ok('ACTIVE'));
      renderStatus('FAILED');
      await act(async () => {
        screen.getByRole('button', { name: /check again/i }).click();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(statusRegion()).toHaveTextContent(/we are setting up your store/i);
      await advance(POLL_MAX_MS);
      expect(statusRegion()).toHaveTextContent(/your store is ready/i);
    });
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

describe('Retry setup on a FAILED store (KAN-242)', () => {
  const retryButton = () => screen.queryByRole('button', { name: /retry setup/i });
  const clickRetry = async () => {
    await act(async () => {
      screen.getByRole('button', { name: /retry setup/i }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.retryProvisioningAction.mockResolvedValue({ success: true, data: { attempt: 1 } });
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('offers Retry setup next to Check again, outside the live region', () => {
    renderStatus('FAILED');

    expect(retryButton()).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
    expect(statusRegion()).not.toContainElement(retryButton());
  });

  it.each(['PROVISIONING', 'ACTIVE', 'SUSPENDED', 'UNKNOWN'] as const)(
    'does not offer it when the status is %s',
    (status) => {
      renderStatus(status);
      expect(retryButton()).toBeNull();
    }
  );

  it('queues the retry through the server action and shows setting-up progress', async () => {
    renderStatus('FAILED');

    await clickRetry();

    expect(mocks.retryProvisioningAction).toHaveBeenCalledWith(STORE_ID);
    expect(statusRegion()).toHaveTextContent(/we are setting up your store/i);
    expect(statusRegion()).not.toHaveTextContent(/could not finish/i);
    expect(retryButton()).toBeNull();
    expect(screen.getByTestId('provisioning-pill')).toHaveTextContent('Setting up');
  });

  it('keeps polling after the retry and shows ready when the store turns ACTIVE', async () => {
    mocks.getStoreStatusAction
      .mockResolvedValueOnce(ok('PROVISIONING'))
      .mockResolvedValue(ok('ACTIVE'));
    renderStatus('FAILED');

    await clickRetry();
    await advance(POLL_MAX_MS);

    expect(statusRegion()).toHaveTextContent(/your store is ready/i);
    expect(screen.getByRole('link', { name: /open dashboard/i })).toBeInTheDocument();
  });

  it('offers the retry again when the new run fails too', async () => {
    mocks.getStoreStatusAction.mockResolvedValue(ok('FAILED'));
    renderStatus('FAILED');

    await clickRetry();
    await advance(POLL_MAX_MS);

    expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
    expect(retryButton()).toBeInTheDocument();
  });

  it('sends one request for a double click', async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.retryProvisioningAction.mockImplementation(() => new Promise((done) => (resolve = done)));
    renderStatus('FAILED');

    await act(async () => {
      const button = screen.getByRole('button', { name: /retry setup/i });
      button.click();
      button.click();
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => resolve({ success: true, data: { attempt: 1 } }));

    expect(mocks.retryProvisioningAction).toHaveBeenCalledTimes(1);
  });

  it('hides Retry at the cap and keeps the contact-support copy and Check again', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'limit' });
    renderStatus('FAILED');

    await clickRetry();

    expect(retryButton()).toBeNull();
    expect(screen.getByTestId('store-status')).toHaveTextContent(/contact support/i);
    expect(screen.getByTestId('store-status')).toHaveTextContent(STORE_ID);
    expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
    expect(statusRegion()).toHaveTextContent(/tried the maximum number of times/i);
  });

  it.each([
    ['rate_limited', /too many attempts/i],
    ['unavailable', /could not retry/i],
  ])('shows a fixed message for %s and keeps the button', async (reason, message) => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason });
    renderStatus('FAILED');

    await clickRetry();

    expect(statusRegion()).toHaveTextContent(message);
    expect(statusRegion()).toHaveTextContent(/could not finish setting up/i);
    expect(retryButton()).toBeInTheDocument();
  });

  it('shows the session-expired text when the session is gone', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, code: 'unauthorized' });
    renderStatus('FAILED');

    await clickRetry();

    expect(statusRegion()).toHaveTextContent(/session/i);
  });

  it('re-reads the status when the store is no longer FAILED', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'not_failed' });
    mocks.getStoreStatusAction.mockResolvedValue(ok('ACTIVE'));
    renderStatus('FAILED');

    await clickRetry();

    expect(mocks.getStoreStatusAction).toHaveBeenCalledWith(STORE_ID);
    expect(statusRegion()).toHaveTextContent(/your store is ready/i);
  });

  it('shows an error when the action itself rejects', async () => {
    mocks.retryProvisioningAction.mockRejectedValue(new Error('stale deployment'));
    renderStatus('FAILED');

    await clickRetry();

    expect(statusRegion()).toHaveTextContent(/could not retry/i);
    expect(retryButton()).toBeInTheDocument();
  });
});

describe('Retry setup: forbidden, pending label and focus (KAN-242 review)', () => {
  const retryButton = () => screen.queryByRole('button', { name: /retry/i });
  const clickRetry = async () => {
    await act(async () => {
      screen.getByRole('button', { name: /retry setup/i }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.getStoreStatusAction.mockResolvedValue(ok('PROVISIONING'));
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('hides Retry for a caller who may not retry, and says who can', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'forbidden' });
    renderStatus('FAILED');

    await clickRetry();

    expect(retryButton()).toBeNull();
    expect(statusRegion()).toHaveTextContent(/owner or admin/i);
    expect(screen.getByRole('button', { name: /check again/i })).toBeInTheDocument();
    expect(screen.getByTestId('store-status')).toHaveTextContent(/contact support/i);
  });

  it('labels the button Retrying... while the request is pending', async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.retryProvisioningAction.mockImplementation(() => new Promise((done) => (resolve = done)));
    renderStatus('FAILED');

    await act(async () => {
      screen.getByRole('button', { name: /retry setup/i }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole('button', { name: /retrying/i })).toHaveAttribute(
      'aria-disabled',
      'true'
    );

    await act(async () => resolve({ success: false, reason: 'unavailable' }));
    expect(screen.getByRole('button', { name: /retry setup/i })).toBeInTheDocument();
  });

  it.each([
    ['success', { success: true, data: { attempt: 1 } }],
    ['limit', { success: false, reason: 'limit' }],
    ['forbidden', { success: false, reason: 'forbidden' }],
  ])('moves focus to the status region when the button goes away (%s)', async (_name, result) => {
    mocks.retryProvisioningAction.mockResolvedValue(result);
    renderStatus('FAILED');
    screen.getByRole('button', { name: /retry setup/i }).focus();

    await clickRetry();

    expect(statusRegion()).toHaveFocus();
  });

  it('leaves focus on the button when it stays (a retryable failure)', async () => {
    mocks.retryProvisioningAction.mockResolvedValue({ success: false, reason: 'unavailable' });
    renderStatus('FAILED');
    const button = screen.getByRole('button', { name: /retry setup/i });
    button.focus();

    await clickRetry();

    expect(screen.getByRole('button', { name: /retry setup/i })).toHaveFocus();
    expect(statusRegion()).not.toHaveFocus();
  });
});

describe('ProvisioningStatus onReady (KAN-254)', () => {
  afterEach(() => cleanup());

  it('calls onReady once when ready, even when the parent passes a new callback', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(
      <ProvisioningStatus
        storeId={STORE_ID}
        storeName="Acme Shop"
        initialStatus="ACTIVE"
        onReady={first}
      />
    );
    rerender(
      <ProvisioningStatus
        storeId={STORE_ID}
        storeName="Acme Shop"
        initialStatus="ACTIVE"
        onReady={second}
      />
    );

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
  });

  it('does not call onReady while the store is still being set up', () => {
    const onReady = vi.fn();
    render(
      <ProvisioningStatus
        storeId={STORE_ID}
        storeName="Acme Shop"
        initialStatus="PROVISIONING"
        onReady={onReady}
      />
    );
    expect(onReady).not.toHaveBeenCalled();
  });
});

describe('ProvisioningStatus dialog variant (KAN-254)', () => {
  afterEach(() => cleanup());

  it('focuses the status and drops the page link and "this page" copy', () => {
    render(
      <ProvisioningStatus
        storeId={STORE_ID}
        storeName="Acme Shop"
        initialStatus="PROVISIONING"
        variant="dialog"
      />
    );
    expect(screen.getByRole('status')).toHaveFocus();
    expect(screen.getByText('Acme Shop is being created. This updates by itself.')).toBeVisible();
  });

  it('shows no "Open dashboard" link when ready', () => {
    render(
      <ProvisioningStatus
        storeId={STORE_ID}
        storeName="Acme Shop"
        initialStatus="ACTIVE"
        variant="dialog"
      />
    );
    expect(screen.getByText('Your store is ready')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Open dashboard' })).not.toBeInTheDocument();
  });
});
