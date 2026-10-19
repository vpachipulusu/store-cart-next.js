'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import {
  getConnectStatusAction,
  startConnectOnboardingAction,
  type ConnectStatus,
} from '@/app/actions/connect-actions';
import { Panel } from '@/components/dashboard/overview/panel';
import { PanelHint } from '@/components/dashboard/settings/form-page';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';

type Load = { state: 'loading' } | { state: 'failed'; message: string } | { state: 'ready' };

const RETURN_NOTICES = {
  return:
    'Thanks. Stripe may take a moment to confirm your details; this page shows the latest status.',
  refresh: 'Your setup link expired. Continue onboarding to get a new one.',
} as const;

const START_FAILED = 'We could not start payment setup. Please try again.';

/** Stripe Connect onboarding returns to this page with `?connect=return` or `?connect=refresh`. */
function readReturnMarker(): 'return' | 'refresh' | null {
  const marker = new URLSearchParams(window.location.search).get('connect');
  return marker === 'return' || marker === 'refresh' ? marker : null;
}

/** Only navigate to an https Stripe URL: the link comes from our backend, but a navigation is never worth trusting blindly. */
function isStripeUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === 'https:' &&
      (url.hostname === 'stripe.com' || url.hostname.endsWith('.stripe.com'))
    );
  } catch {
    return false;
  }
}

interface Pill {
  variant: StatusPillVariant;
  label: string;
}

function capabilityPill(enabled: boolean, on: string, off: string): Pill {
  return enabled ? { variant: 'good', label: on } : { variant: 'warn', label: off };
}

function StatusRow({ label, pill }: { label: string; pill: Pill }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <span className="text-sm">{label}</span>
      <StatusPill variant={pill.variant}>{pill.label}</StatusPill>
    </li>
  );
}

export function ConnectPaymentsPanel() {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [isStarting, setIsStarting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // The panel only mounts in the browser (after the settings page loads), so reading the URL here is safe.
  const [marker] = useState(() => (typeof window === 'undefined' ? null : readReturnMarker()));
  const notice = marker ? RETURN_NOTICES[marker] : null;

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const result = await getConnectStatusAction();
        if (cancelled) return;
        if (!result.success) {
          setLoad({ state: 'failed', message: result.error });
          return;
        }
        setStatus(result.data);
        setLoad({ state: 'ready' });
      } catch {
        if (cancelled) return;
        setLoad({ state: 'failed', message: 'We could not load your payment status.' });
      }
    }

    void loadStatus();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function retry() {
    setLoad({ state: 'loading' });
    setAttempt((count) => count + 1);
  }

  async function startOnboarding() {
    setIsStarting(true);
    setActionError(null);
    try {
      const result = await startConnectOnboardingAction();
      if (!result.success) {
        setActionError(result.error);
        setIsStarting(false);
        return;
      }
      if (!isStripeUrl(result.data.url)) {
        setActionError(START_FAILED);
        setIsStarting(false);
        return;
      }
      // Stay disabled while the browser navigates away, so a second click cannot create a second link.
      window.location.assign(result.data.url);
    } catch {
      setActionError(START_FAILED);
      setIsStarting(false);
    }
  }

  if (load.state === 'loading') {
    return (
      <Panel title="Payments" titleId="payments-title" busy>
        <p role="status" className="sr-only">
          Loading payment status
        </p>
        <Skeleton className="h-24 w-full" />
      </Panel>
    );
  }

  if (load.state === 'failed' || !status) {
    return (
      <Panel title="Payments" titleId="payments-title">
        <div role="alert" className="space-y-3">
          <p className="text-sm">
            {load.state === 'failed' ? load.message : 'We could not load your payment status.'}
          </p>
          <Button type="button" variant="outline" onClick={retry}>
            Try again
          </Button>
        </div>
      </Panel>
    );
  }

  const complete = status.chargesEnabled && status.payoutsEnabled && status.detailsSubmitted;

  return (
    <Panel title="Payments" titleId="payments-title">
      <PanelHint>
        Accept card payments from your customers. Setup happens on Stripe, and you can leave and
        come back at any time.
      </PanelHint>
      <ul className="divide-y divide-border" aria-label="Payment setup status">
        <StatusRow
          label="Account"
          pill={
            status.hasAccount
              ? { variant: 'info', label: 'Created' }
              : { variant: 'neutral', label: 'Not set up' }
          }
        />
        <StatusRow
          label="Details submitted"
          pill={capabilityPill(status.detailsSubmitted, 'Submitted', 'Incomplete')}
        />
        <StatusRow
          label="Card payments"
          pill={capabilityPill(status.chargesEnabled, 'Enabled', 'Not enabled')}
        />
        <StatusRow
          label="Payouts"
          pill={capabilityPill(status.payoutsEnabled, 'Enabled', 'Not enabled')}
        />
      </ul>

      {notice && (
        <p role="status" className="mt-3 text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      {!status.chargesEnabled && (
        <p className="mt-3 text-sm text-muted-foreground">
          Checkout stays off until card payments are enabled.
        </p>
      )}
      {actionError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {actionError}
        </p>
      )}

      {!complete && (
        <Button type="button" className="mt-4" onClick={startOnboarding} disabled={isStarting}>
          {isStarting && <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />}
          {status.hasAccount ? 'Continue onboarding' : 'Start onboarding'}
        </Button>
      )}
    </Panel>
  );
}
