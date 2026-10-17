'use client';

import { useState, useTransition } from 'react';
import { RefreshCw } from 'lucide-react';

import { syncStripeSubscriptionsAction } from '@/app/actions/admin/analytics-actions';
import { Button } from '@/components/ui/button';
import { Panel } from '@/components/dashboard/overview/panel';
// Type-only: the module is server-only, so this import must stay erased.
import type { SyncData } from '@/lib/api/admin-analytics';

const SYNC_FAILED_MESSAGE = 'The check could not be completed. Please try again.';

const DRIFT_LABELS: Record<SyncData['drifts'][number]['kind'], string> = {
  unmatched: 'No matching organisation',
  subscription_id: 'Different subscription',
  status: 'Status differs',
  plan: 'Plan differs',
  cancel_at_period_end: 'Cancellation flag differs',
  missing_in_stripe: 'Not found in Stripe',
};

/** Runs the bulk Stripe reconciliation and lists what differs (KAN-119). It changes no subscription. */
export function SyncPanel() {
  const [pending, startTransition] = useTransition();
  const [report, setReport] = useState<SyncData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = () =>
    startTransition(async () => {
      try {
        const result = await syncStripeSubscriptionsAction();
        setError(result.success ? null : result.error);
        setReport(result.success ? result.data : null);
      } catch {
        setError(SYNC_FAILED_MESSAGE);
        setReport(null);
      }
    });

  return (
    <Panel
      title="Stripe reconciliation"
      titleId="admin-stripe-sync"
      busy={pending}
      action={
        <Button variant="outline" onClick={run} disabled={pending}>
          <RefreshCw
            aria-hidden="true"
            className={`mr-2 size-4 ${pending ? 'animate-spin' : ''}`}
          />
          {pending ? 'Checking…' : 'Check against Stripe'}
        </Button>
      }
    >
      <p className="text-sm text-muted-foreground">
        Compares every Stripe subscription with the stored organisation billing state. It reports
        differences only; Stripe webhooks remain the only thing that changes a subscription.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div aria-live="polite">{report ? <SyncReport report={report} /> : null}</div>
    </Panel>
  );
}

function SyncReport({ report }: { report: SyncData }) {
  return (
    <div className="mt-3 space-y-3 text-sm">
      <p>
        Read {report.stripe_subscriptions} Stripe subscriptions: {report.in_sync} in sync,{' '}
        {report.drift_count} differ
        {report.historical_ignored > 0 ? `, ${report.historical_ignored} old ones ignored` : ''}.
      </p>
      {report.skipped_rows > 0 ? (
        <p className="text-muted-foreground">
          {report.skipped_rows} Stripe row(s) could not be read, so the check for subscriptions
          missing from Stripe was skipped.
        </p>
      ) : null}
      {report.truncated ? (
        <p className="text-muted-foreground">
          Stripe has more subscriptions than one check reads, so the result is partial.
        </p>
      ) : null}
      {report.drifts.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {report.drifts.map((drift, index) => (
            <li
              key={`${index}:${drift.kind}:${drift.subscription_id ?? drift.organization_id}`}
              className="flex flex-wrap justify-between gap-2 px-3 py-2"
            >
              <span>{DRIFT_LABELS[drift.kind]}</span>
              <span className="font-mono text-xs text-muted-foreground">
                {drift.organization_id ?? 'unknown organisation'} · {drift.subscription_id ?? '—'} ·
                Stripe {drift.stripe_status ?? '—'} / stored {drift.local_status ?? '—'}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {report.drift_count > report.drifts.length ? (
        <p className="text-muted-foreground">
          Showing the first {report.drifts.length} of {report.drift_count}.
        </p>
      ) : null}
    </div>
  );
}
