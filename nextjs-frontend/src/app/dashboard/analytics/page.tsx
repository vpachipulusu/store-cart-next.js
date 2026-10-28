import { Card, CardContent } from '@/components/ui/card';
import { AnalyticsRangeForm } from '@/components/dashboard/analytics/analytics-range-form';
import {
  AnalyticsReport,
  AnalyticsRoleNotice,
} from '@/components/dashboard/analytics/analytics-report';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import { StoreSetupState } from '@/components/dashboard/store-setup-state';
import {
  analyticsHref,
  formatRange,
  parseAnalyticsQuery,
  type AnalyticsSearchParams,
} from '@/lib/analytics/query';
import { analyticsErrorMessage, fetchStoreAnalytics, isRoleRefusal } from '@/lib/api/analytics';
import { logger } from '@/lib/logger';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { isStoreInSetup } from '@/lib/stores/provisioning';

export const metadata = { title: 'Analytics' };

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<AnalyticsSearchParams>;
}) {
  const query = parseAnalyticsQuery(await searchParams);

  // The layout already explains a missing store or a failed store list, so there is nothing to show here.
  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;
  if (isStoreInSetup(selection.selected.status)) {
    const { id, name, status } = selection.selected;
    return <StoreSetupState storeId={id} storeName={name} status={status} />;
  }

  const result = await fetchStoreAnalytics(selection.selected.id, query);
  if (!result.success && result.status !== 403 && result.status !== 422) {
    logger.error('Analytics page: report failed', { status: result.status });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">
          Sales, orders and top products for {selection.selected.name}
        </p>
      </div>

      {!result.success && isRoleRefusal(result) ? (
        <AnalyticsRoleNotice />
      ) : (
        <>
          <Card>
            <CardContent className="space-y-3 pt-6">
              <AnalyticsRangeForm
                from={result.success ? result.data.start_date : (query.from ?? '')}
                to={result.success ? result.data.end_date : (query.to ?? '')}
                bucket={query.bucket}
              />
              {result.success ? (
                <p className="text-sm text-muted-foreground" data-testid="analytics-range">
                  {`${formatRange(result.data.start_date, result.data.end_date)} (UTC). Paid, fulfilled and refunded orders; net sales are after refunds.`}
                </p>
              ) : result.status === 422 ? (
                // The range itself was refused: retrying the same URL cannot help, the form above can.
                <p
                  role="alert"
                  className="rounded-lg border border-destructive/50 p-4 text-sm text-destructive"
                >
                  {analyticsErrorMessage(result)}
                </p>
              ) : (
                <ProductsLoadError
                  message={analyticsErrorMessage(result)}
                  retryHref={analyticsHref(query)}
                />
              )}
            </CardContent>
          </Card>
          {result.success ? <AnalyticsReport report={result.data} /> : null}
        </>
      )}
    </div>
  );
}
