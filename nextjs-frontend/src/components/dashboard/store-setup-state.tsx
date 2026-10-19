'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { retryProvisioningAction } from '@/app/actions/onboarding-actions';
import { SESSION_EXPIRED_MESSAGE } from '@/lib/onboarding/schema';
import {
  RETRY_LIMIT_MESSAGE,
  RETRY_MESSAGES,
  STUCK_AFTER_MINUTES,
  type SetupStatus,
} from '@/lib/stores/provisioning';

type StoreSetupStateProps = {
  storeId: string;
  storeName: string;
  status: SetupStatus;
};

const TOO_SOON_MESSAGE = `Your store is still being set up. If it is not ready ${STUCK_AFTER_MINUTES} minutes after you created it, retry setup.`;
const LIMIT_MESSAGE = `${RETRY_LIMIT_MESSAGE} Please contact support.`;

/**
 * Shown on store-scoped dashboard pages while the selected store has no database (KAN-255): PROVISIONING or FAILED.
 * Replaces the generic "could not be reached" error. "Retry setup" is the merchant re-run (KAN-242); the backend
 * decides whether a PROVISIONING store is stuck (over 15 minutes) and answers `not_failed` while it may still be
 * running, so offering the button for both states is safe.
 */
export function StoreSetupState({ storeId, storeName, status }: StoreSetupStateProps) {
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // Set synchronously, so two clicks in the same tick cannot both send a retry.
  const inFlight = useRef(false);
  const statusHref = `/dashboard/onboarding/status/${encodeURIComponent(storeId)}`;
  const failed = status === 'FAILED';

  async function handleRetry() {
    if (inFlight.current) return;
    inFlight.current = true;
    setRetrying(true);
    setProblem(null);
    try {
      const result = await retryProvisioningAction(storeId);
      if (result.success) {
        router.push(statusHref);
        return;
      }
      setProblem(retryProblem(result));
    } catch {
      setProblem(RETRY_MESSAGES.unavailable);
    } finally {
      inFlight.current = false;
      setRetrying(false);
    }
  }

  return (
    <section aria-labelledby="store-setup-heading" className="container max-w-2xl space-y-4 py-10">
      <StatusPill variant={failed ? 'crit' : 'warn'}>
        {failed ? 'Needs attention' : 'Setting up'}
      </StatusPill>
      <h1 id="store-setup-heading" className="text-2xl font-semibold">
        {failed ? `Setting up ${storeName} failed` : `${storeName} is still being set up`}
      </h1>
      <p className="text-muted-foreground">
        {failed
          ? 'We could not finish creating the database for this store. Retry setup to try again.'
          : 'Products, orders and store settings open once setup finishes. This usually takes under a minute.'}
      </p>
      <div role="status" aria-live="polite" className="text-sm">
        {problem}
      </div>
      <div className="flex flex-wrap gap-3">
        <Button onClick={handleRetry} disabled={retrying}>
          {retrying && <Loader2 aria-hidden="true" className="me-2 size-4 animate-spin" />}
          Retry setup
        </Button>
        <Button variant="outline" asChild>
          <Link href={statusHref}>View setup progress</Link>
        </Button>
      </div>
    </section>
  );
}

type RetryFailure = Exclude<Awaited<ReturnType<typeof retryProvisioningAction>>, { success: true }>;

function retryProblem(result: RetryFailure): string {
  if (result.code === 'unauthorized') return SESSION_EXPIRED_MESSAGE;
  switch (result.reason) {
    case 'not_failed':
      return TOO_SOON_MESSAGE;
    case 'limit':
      return LIMIT_MESSAGE;
    case 'forbidden':
    case 'rate_limited':
      return RETRY_MESSAGES[result.reason];
    default:
      return RETRY_MESSAGES.unavailable;
  }
}
