'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { getStoreStatusAction, retryProvisioningAction } from '@/app/actions/onboarding-actions';
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
/** Mirrors STUCK_AFTER in fastapi_backend/app/services/admin_stores.py: the backend re-runs a quiet store only after this long. */
const RETRY_AVAILABLE_AFTER_MINUTES = 15;
const TOO_SOON_MESSAGE =
  'Your store is still being set up. Please wait a few minutes, then check again.';
const RETRY_LIMIT_MESSAGE = 'We have already tried the maximum number of times.';
const RETRY_MESSAGES = {
  rate_limited: 'Too many attempts. Wait a few minutes and try again.',
  forbidden: 'Only an owner or admin of this business can retry the setup.',
  unavailable: 'We could not retry the setup. Please try again.',
} as const;

type ProvisioningStatusProps = {
  storeId: string;
  storeName: string;
  /** The status the server rendered the page with, or UNKNOWN when the backend could not be reached. */
  initialStatus: StoreStatus | 'UNKNOWN';
  /** Called once when the store first shows as ready (the dashboard "New store" dialog selects it, KAN-254). */
  onReady?: () => void;
};

/**
 * Shows a new store's provisioning progress (KAN-60): PROVISIONING is "setting up", ACTIVE is ready. Anything
 * else, or repeated failed checks, shows a message with a retry. FAILED (KAN-191) has its own copy: the job gave
 * up, nothing the merchant can do re-runs it yet, so its button is "Check again" and only re-reads the status.
 * Polls the server action with backoff and clears its timers on unmount or when the store settles. The text lives
 * in one persistent polite live region so each change (including "ready" and "still not finished") is announced;
 * the retry and dashboard controls sit outside it.
 */
export function ProvisioningStatus({
  storeId,
  storeName,
  initialStatus,
  onReady,
}: ProvisioningStatusProps) {
  const [status, setStatus] = useState<StoreStatus | 'UNKNOWN'>(initialStatus);
  const [problem, setProblem] = useState<string | null>(null);
  /** Polling used up its attempts while the store was still PROVISIONING: the job may have stopped (KAN-248). */
  const [gaveUp, setGaveUp] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [coolingDown, setCoolingDown] = useState(false);
  /** True once a manual check came back FAILED again, so the unchanged screen still gives feedback. */
  const [stillFailed, setStillFailed] = useState(false);
  /** A retry request is in flight (a second click is ignored), and what the last one said (KAN-242). */
  const [retrying, setRetrying] = useState(false);
  const retryingRef = useRef(false);
  const [retryProblem, setRetryProblem] = useState<string | null>(null);
  /** The backend refused because the store was already retried the maximum number of times. */
  const [retryLimitReached, setRetryLimitReached] = useState(false);
  /** The caller is not an owner or admin, so the button is pointless for them. */
  const [retryForbidden, setRetryForbidden] = useState(false);
  /** Whether the store was FAILED when the user pressed the button; only then is "still" accurate. */
  const checkedFromFailedRef = useRef(false);
  const dashboardLinkRef = useRef<HTMLAnchorElement>(null);
  /** Set when a stalled-state re-read turns the store ACTIVE, so focus follows the button that unmounts. */
  const focusDashboardRef = useRef(false);
  /** The focused "Retry setup" button unmounts on success or at the cap; focus moves here so it is not lost. */
  const statusRegionRef = useRef<HTMLDivElement>(null);
  /** The latest `onReady`, so a new callback identity from the parent neither re-fires nor goes stale. */
  const onReadyRef = useRef(onReady);
  const readyNotifiedRef = useRef(false);

  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  useEffect(() => {
    if (initialStatus !== 'PROVISIONING' && retryCount === 0) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let failures = 0;

    const schedule = () => {
      if (attempt >= POLL_MAX_ATTEMPTS) {
        setProblem(SLOW_MESSAGE);
        setGaveUp(true);
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
      if (checkedFromFailedRef.current && result.data.status === 'FAILED') setStillFailed(true);
      if (result.data.status === 'PROVISIONING') schedule();
      else if (result.data.status !== 'ACTIVE' && result.data.status !== 'FAILED') {
        setProblem(UNAVAILABLE_MESSAGE);
      }
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
    checkedFromFailedRef.current = status === 'FAILED';
    setCoolingDown(true);
    setProblem(null);
    setGaveUp(false);
    setRetryProblem(null);
    setStillFailed(false);
    setRetryCount((count) => count + 1);
  };

  const focusStatusRegion = () => statusRegionRef.current?.focus();
  const stalled = status === 'PROVISIONING' && gaveUp;

  /**
   * The backend only re-runs a store that has made no progress for a while, so a retry can come too early. Read the
   * status once: a store that has since finished or failed shows that; one still PROVISIONING is told to wait.
   */
  const recheckStalled = async () => {
    const check = await getStoreStatusAction(storeId);
    if (!check.success) {
      setRetryProblem(RETRY_MESSAGES.unavailable);
      return;
    }
    setStatus(check.data.status);
    if (check.data.status === 'PROVISIONING') {
      setRetryProblem(TOO_SOON_MESSAGE);
    } else {
      setProblem(null);
      setGaveUp(false);
      focusDashboardRef.current = check.data.status === 'ACTIVE';
    }
  };

  /** Re-runs the job (KAN-242). Success shows the normal setting-up progress and polls until it settles. */
  const handleSetupRetry = async () => {
    if (retryingRef.current) return;
    retryingRef.current = true;
    setRetrying(true);
    setRetryProblem(null);
    try {
      const result = await retryProvisioningAction(storeId);
      if (result.success) {
        checkedFromFailedRef.current = false;
        setStatus('PROVISIONING');
        setProblem(null);
        setGaveUp(false);
        setStillFailed(false);
        setRetryCount((count) => count + 1);
        focusStatusRegion(); // the button unmounts: the setting-up text is announced from here
      } else if (result.code === 'unauthorized') {
        setRetryProblem(SESSION_EXPIRED_MESSAGE);
      } else if (result.reason === 'limit') {
        setRetryLimitReached(true);
        focusStatusRegion();
      } else if (result.reason === 'forbidden') {
        setRetryProblem(RETRY_MESSAGES.forbidden);
        setRetryForbidden(true);
        focusStatusRegion();
      } else if (stalled && result.reason === 'not_failed') {
        await recheckStalled();
      } else if (result.reason === 'not_failed' || result.reason === 'not_found') {
        // The store changed under us: show what it is now instead of guessing.
        checkedFromFailedRef.current = false;
        setGaveUp(false);
        setRetryCount((count) => count + 1);
      } else {
        setRetryProblem(RETRY_MESSAGES[result.reason ?? 'unavailable']);
      }
    } catch {
      // A dropped connection or a stale deployment rejects the action.
      setRetryProblem(RETRY_MESSAGES.unavailable);
    } finally {
      retryingRef.current = false;
      setRetrying(false);
    }
  };

  // FAILED is the provisioning job giving up. An owner or admin can re-run it (KAN-242, "Retry setup") until the
  // attempt cap; after that, or for anyone else, the screen says to contact support. "Check again" only re-reads
  // the status (an admin re-run, KAN-200, may have turned it ACTIVE).
  // A failed check while FAILED keeps this explanation and adds the problem as an extra line.
  const provisioningFailed = status === 'FAILED';
  const message =
    problem ??
    (status === 'UNKNOWN'
      ? CHECK_FAILED_MESSAGE
      : status === 'SUSPENDED' || status === 'ARCHIVED'
        ? UNAVAILABLE_MESSAGE
        : null);
  const ready = message === null && status === 'ACTIVE';
  const needsAttention = message !== null || provisioningFailed;

  useEffect(() => {
    if (!ready || readyNotifiedRef.current) return;
    readyNotifiedRef.current = true;
    onReadyRef.current?.();
  }, [ready]);

  // The button that was focused unmounts when a check turns the store ACTIVE, so focus moves to the new link.
  useEffect(() => {
    if (ready && (retryCount > 0 || focusDashboardRef.current)) dashboardLinkRef.current?.focus();
  }, [ready, retryCount]);

  return (
    <div className="flex flex-col items-start gap-4" data-testid="store-status">
      <div
        ref={statusRegionRef}
        tabIndex={-1}
        role="status"
        aria-live="polite"
        className="flex flex-col items-start gap-2 outline-none"
      >
        {provisioningFailed ? (
          <>
            <StatusPill variant="crit" data-testid="provisioning-pill">
              Needs attention
            </StatusPill>
            <p className="font-medium">We could not finish setting up your store</p>
            {problem !== null && <p className="text-sm">{problem}</p>}
            {retryProblem !== null && <p className="text-sm">{retryProblem}</p>}
            {retryLimitReached && <p className="text-sm">{RETRY_LIMIT_MESSAGE}</p>}
            {stillFailed && problem === null && (
              // Keyed per check so each repeat check is announced again.
              <p key={retryCount} className="text-sm">
                Still not finished. We checked just now.
              </p>
            )}
          </>
        ) : message !== null ? (
          <>
            <StatusPill variant="crit" data-testid="provisioning-pill">
              Needs attention
            </StatusPill>
            <p className="font-medium">{message}</p>
            {stalled && !retryLimitReached && !retryForbidden && (
              <p className="text-sm text-muted-foreground">
                If your store is still not ready about {RETRY_AVAILABLE_AFTER_MINUTES} minutes after
                you created it, use Retry setup below.
              </p>
            )}
            {stalled && retryProblem !== null && <p className="text-sm">{retryProblem}</p>}
            {stalled && retryLimitReached && (
              <>
                <p className="text-sm">{RETRY_LIMIT_MESSAGE}</p>
                <p className="text-sm">
                  Please contact support and include this reference:{' '}
                  <span className="font-mono">{storeId}</span>
                </p>
              </>
            )}
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
      {provisioningFailed && (
        // Outside the live region so the support details are not read out again on every status change.
        <>
          <p className="text-sm text-muted-foreground">
            Setting up {storeName} did not complete. Please contact support and include your store
            name, the reference below and the time you created it so we can finish the setup. If it
            has already been fixed, check again below.
          </p>
          <p className="text-sm text-muted-foreground">
            Reference: <span className="font-mono">{storeId}</span>
          </p>
        </>
      )}
      {needsAttention && (
        <div className="flex flex-wrap items-center gap-3">
          {(provisioningFailed || stalled) && !retryLimitReached && !retryForbidden && (
            <Button
              type="button"
              onClick={() => void handleSetupRetry()}
              aria-disabled={retrying}
              className="min-h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
            >
              {retrying ? 'Retrying...' : 'Retry setup'}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={handleRetry}
            aria-disabled={coolingDown}
            className="min-h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
          >
            {provisioningFailed || stalled ? 'Check again' : 'Try again'}
          </Button>
        </div>
      )}
      {ready && (
        <Button asChild className="min-h-11">
          <Link ref={dashboardLinkRef} href="/dashboard">
            Open dashboard
          </Link>
        </Button>
      )}
    </div>
  );
}
