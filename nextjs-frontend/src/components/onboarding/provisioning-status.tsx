'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { getStoreStatusAction } from '@/app/actions/onboarding-actions';
import { SESSION_EXPIRED_MESSAGE } from '@/lib/onboarding/schema';
import type { StoreStatus } from '@/lib/api/onboarding';

/** Poll delays grow by 1.5x from 2s to a 15s cap, so a slow provisioning job is not hammered. */
export const POLL_INITIAL_MS = 2000;
export const POLL_MAX_MS = 15000;
const POLL_FACTOR = 1.5;
/** About five minutes of polling at the capped delay; then the user is offered a manual retry. */
export const POLL_MAX_ATTEMPTS = 24;
/** A single dropped request is retried on the backoff schedule; only this many in a row show an error. */
export const POLL_MAX_FAILURES = 3;
/** Manual retries are spaced out so they cannot be used to poll the backend in a tight loop. */
export const RETRY_COOLDOWN_MS = 3000;

export function nextPollDelay(attempt: number): number {
  return Math.min(POLL_MAX_MS, Math.round(POLL_INITIAL_MS * POLL_FACTOR ** attempt));
}

const UNAVAILABLE_MESSAGE = 'This store is not available right now.';
const SLOW_MESSAGE = 'Setting up your store is taking longer than expected.';
const CHECK_FAILED_MESSAGE = 'We could not check your store. Please try again.';

type ProvisioningStatusProps = {
  storeId: string;
  storeName: string;
  /** The status the server rendered the page with, or UNKNOWN when the backend could not be reached. */
  initialStatus: StoreStatus | 'UNKNOWN';
};

/**
 * Shows a new store's provisioning progress (KAN-60): PROVISIONING is "setting up", ACTIVE is ready. Anything
 * else, or repeated failed checks, shows a message with a retry. Polls the server action with backoff and clears
 * its timers on unmount or when the store settles. The text lives in one persistent polite live region so each
 * change (including "ready") is announced; the retry and dashboard controls sit outside it.
 */
export function ProvisioningStatus({ storeId, storeName, initialStatus }: ProvisioningStatusProps) {
  const [status, setStatus] = useState<StoreStatus | 'UNKNOWN'>(initialStatus);
  const [problem, setProblem] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [coolingDown, setCoolingDown] = useState(false);

  useEffect(() => {
    if (initialStatus !== 'PROVISIONING' && retryCount === 0) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let failures = 0;

    const schedule = () => {
      if (attempt >= POLL_MAX_ATTEMPTS) {
        setProblem(SLOW_MESSAGE);
        return;
      }
      timer = setTimeout(poll, nextPollDelay(attempt));
      attempt += 1;
    };

    // A transient failure keeps polling; the error shows only after POLL_MAX_FAILURES in a row.
    const noteFailure = () => {
      failures += 1;
      if (failures >= POLL_MAX_FAILURES) setProblem(CHECK_FAILED_MESSAGE);
      else schedule();
    };

    async function poll() {
      let result: Awaited<ReturnType<typeof getStoreStatusAction>>;
      try {
        result = await getStoreStatusAction(storeId);
      } catch {
        // A dropped connection or a stale deployment rejects the action.
        if (!cancelled) noteFailure();
        return;
      }
      if (cancelled) return;
      if (!result.success) {
        if (result.code === 'unauthorized') setProblem(SESSION_EXPIRED_MESSAGE);
        else if (result.notFound) setProblem(UNAVAILABLE_MESSAGE);
        else noteFailure();
        return;
      }
      failures = 0;
      setStatus(result.data.status);
      if (result.data.status === 'PROVISIONING') schedule();
      else if (result.data.status !== 'ACTIVE') setProblem(UNAVAILABLE_MESSAGE);
    }

    if (retryCount > 0) void poll();
    else schedule();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [storeId, initialStatus, retryCount]);

  useEffect(() => {
    if (!coolingDown) return;
    const timer = setTimeout(() => setCoolingDown(false), RETRY_COOLDOWN_MS);
    return () => clearTimeout(timer);
  }, [coolingDown]);

  const handleRetry = () => {
    if (coolingDown) return;
    setCoolingDown(true);
    setProblem(null);
    setRetryCount((count) => count + 1);
  };

  const message =
    problem ??
    (status === 'UNKNOWN'
      ? CHECK_FAILED_MESSAGE
      : status === 'FAILED' || status === 'SUSPENDED' || status === 'ARCHIVED'
        ? UNAVAILABLE_MESSAGE
        : null);
  const ready = message === null && status === 'ACTIVE';

  return (
    <div className="flex flex-col items-start gap-4" data-testid="store-status">
      <div role="status" aria-live="polite" className="flex flex-col items-start gap-2">
        {message !== null ? (
          <>
            <StatusPill variant="crit" data-testid="provisioning-pill">
              Needs attention
            </StatusPill>
            <p className="font-medium">{message}</p>
          </>
        ) : ready ? (
          <>
            <StatusPill variant="good" data-testid="provisioning-pill">
              Ready
            </StatusPill>
            <p className="font-medium">Your store is ready</p>
            <p className="text-sm text-muted-foreground">{storeName} is set up and ready to use.</p>
          </>
        ) : (
          <>
            <StatusPill variant="warn" data-testid="provisioning-pill">
              Setting up
            </StatusPill>
            <div className="flex items-center gap-2 font-medium">
              <Loader2
                className="h-5 w-5 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              <span>We are setting up your store</span>
            </div>
            <p className="text-sm text-muted-foreground">
              {storeName} is being created. This page updates by itself, so you can leave it open.
            </p>
          </>
        )}
      </div>
      {message !== null && (
        <Button
          type="button"
          variant="outline"
          onClick={handleRetry}
          aria-disabled={coolingDown}
          className="min-h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        >
          Try again
        </Button>
      )}
      {ready && (
        <Button asChild className="min-h-11">
          <Link href="/dashboard">Open dashboard</Link>
        </Button>
      )}
    </div>
  );
}
