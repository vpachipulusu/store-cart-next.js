import { Lock } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { ANALYTICS_FORBIDDEN_MESSAGE, isAnalyticsBucket } from '@/lib/analytics/query';
import type { StoreAnalyticsData } from '@/lib/api/analytics';
import { CurrencyAnalytics } from './currency-analytics';

/** One section per currency with sales, or the empty state. */
export function AnalyticsReport({ report }: { report: StoreAnalyticsData }) {
  if (report.currencies.length === 0) {
    return (
      <Card>
        <CardContent role="status" data-testid="no-sales" className="py-8 pt-8 text-center text-sm">
          <p className="font-medium">No sales in this period.</p>
          <p className="text-muted-foreground">Paid orders appear here. Try a longer range.</p>
        </CardContent>
      </Card>
    );
  }
  const bucket = isAnalyticsBucket(report.bucket) ? report.bucket : 'day';
  return (
    <>
      {report.currencies.map((entry) => (
        <CurrencyAnalytics key={entry.currency} entry={entry} bucket={bucket} />
      ))}
    </>
  );
}

/** STAFF (and any role the backend refuses with 403) see this instead of the figures. */
export function AnalyticsRoleNotice() {
  return (
    <Card>
      <CardContent
        role="status"
        data-testid="analytics-forbidden"
        className="flex flex-col items-center gap-2 py-8 pt-8 text-center text-sm"
      >
        <Lock aria-hidden="true" className="size-5 text-muted-foreground" />
        <p className="font-medium">{ANALYTICS_FORBIDDEN_MESSAGE}</p>
        <p className="text-muted-foreground">
          Store owners and admins can see sales figures. Ask an owner for access.
        </p>
      </CardContent>
    </Card>
  );
}
