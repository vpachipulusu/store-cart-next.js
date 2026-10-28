import { KpiStrip } from '@/components/dashboard/kpi-strip';
import { Skeleton } from '@/components/ui/skeleton';

/** Shown while the server reads the report. */
export default function AnalyticsLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="sr-only" role="status">
          Loading analytics
        </p>
      </div>
      <Skeleton className="h-24 w-full" />
      <KpiStrip
        cells={['Net sales', 'Gross sales', 'Refunds', 'Orders'].map((label) => ({
          id: label,
          label,
          state: 'loading',
        }))}
      />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
