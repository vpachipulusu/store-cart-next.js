'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Loader2, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getStoreStatusAction } from '@/app/actions/onboarding-actions';

/** Poll delays grow by 1.5x from 2s to a 15s cap, so a slow provisioning job is not hammered. */
export const POLL_INITIAL_MS = 2000;
export const POLL_MAX_MS = 15000;
const POLL_FACTOR = 1.5;
/** About five minutes of polling at the capped delay; then the user is offered a manual retry. */
export const POLL_MAX_ATTEMPTS = 24;

export function nextPollDelay(attempt: number): number {
  return Math.min(POLL_MAX_MS, Math.round(POLL_INITIAL_MS * POLL_FACTOR ** attempt));
}

const UNAVAILABLE_MESSAGE = 'This store is not available right now.';
const SLOW_MESSAGE = 'Setting up your store is taking longer than expected.';
const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Please sign in again.';
const CHECK_FAILED_MESSAGE = 'Could not check your store. Please try again.';

type ProvisioningStatusProps = {
  storeId: string;
  storeName: string;
  /** The status the server rendered the page with; polling starts from it. */
  initialStatus: string;
};

/**
 * Shows a new store's provisioning progress (KAN-60): PROVISIONING is "setting up", ACTIVE is ready. Anything
 * else, or a failed check, shows a message with a retry. Polls the server action with backoff and clears its
 * timer on unmount or when the store settles.
 */
export function ProvisioningStatus({ storeId, storeName, initialStatus }: ProvisioningStatusProps) {
  const [status, setStatus] = useState(initialStatus);
  const [problem, setProblem] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    if (initialStatus !== 'PROVISIONING' && retryCount === 0) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const schedule = () => {
      if (attempt >= POLL_MAX_ATTEMPTS) {
        setProblem(SLOW_MESSAGE);
        return;
      }
      timer = setTimeout(poll, nextPollDelay(attempt));
      attempt += 1;
    };

    async function poll() {
      let result: Awaited<ReturnType<typeof getStoreStatusAction>>;
      try {
        result = await getStoreStatusAction(storeId);
      } catch {
        // A dropped connection or a stale deployment rejects the action; offer a retry instead of hanging.
        if (!cancelled) setProblem(CHECK_FAILED_MESSAGE);
        return;
      }
      if (cancelled) return;
      if (!result.success) {
        setProblem(
          result.notFound
            ? UNAVAILABLE_MESSAGE
            : result.error === 'Unauthorized'
              ? SESSION_EXPIRED_MESSAGE
              : result.error
        );
        return;
      }
      setStatus(result.data.status);
      if (result.data.status === 'PROVISIONING') {
        schedule();
      } else if (result.data.status !== 'ACTIVE') {
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

  const handleRetry = () => {
    setProblem(null);
    setRetryCount((count) => count + 1);
  };

  const unavailable =
    problem ?? (status !== 'PROVISIONING' && status !== 'ACTIVE' ? UNAVAILABLE_MESSAGE : null);
  if (unavailable) {
    return (
      <div role="alert" className="flex flex-col items-start gap-4" data-testid="store-status">
        <div className="flex items-center gap-2 font-medium">
          <TriangleAlert className="h-5 w-5 text-destructive" aria-hidden="true" />
          <span>{unavailable}</span>
        </div>
        <Button type="button" variant="outline" onClick={handleRetry} className="min-h-11">
          Try again
        </Button>
      </div>
    );
  }

  if (status === 'ACTIVE') {
    return (
      <div role="status" className="flex flex-col items-start gap-4" data-testid="store-status">
        <div className="flex items-center gap-2 font-medium">
          <CheckCircle2 className="h-5 w-5 text-green-600" aria-hidden="true" />
          <span>Your store is ready</span>
        </div>
        <p className="text-sm text-muted-foreground">{storeName} is set up and ready to use.</p>
        <Button asChild className="min-h-11">
          <Link href="/dashboard">Open dashboard</Link>
        </Button>
      </div>
    );
  }

  return (
    <div role="status" className="flex flex-col items-start gap-2" data-testid="store-status">
      <div className="flex items-center gap-2 font-medium">
        <Loader2 className="h-5 w-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <span>We are setting up your store</span>
      </div>
      <p className="text-sm text-muted-foreground">
        {storeName} is being created. This page updates by itself, so you can leave it open.
      </p>
    </div>
  );
}
