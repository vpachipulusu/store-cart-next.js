import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { KpiStrip } from '@/components/dashboard/kpi-strip';
import type { AnalyticsBucket } from '@/lib/analytics/query';
import { formatMinor } from '@/lib/products/money';
import type { CurrencyAnalyticsData } from '@/lib/api/analytics';
import { SalesChart } from './sales-chart';
import { SalesTable } from './sales-table';
import { TopProducts } from './top-products';

/** Totals, the sales series and the top products for one currency; amounts are never converted. */
export function CurrencyAnalytics({
  entry,
  bucket,
}: {
  entry: CurrencyAnalyticsData;
  bucket: AnalyticsBucket;
}) {
  const { currency, totals, series } = entry;
  const trend = series.map((point) => point.net_sales_minor);
  return (
    <Card data-testid={`analytics-${currency}`}>
      <CardHeader>
        <CardTitle className="text-xl">Sales in {currency}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <KpiStrip
          cells={[
            {
              id: `net-${currency}`,
              label: 'Net sales',
              state: 'ready',
              value: formatMinor(totals.net_sales_minor, currency),
              trend,
            },
            {
              id: `gross-${currency}`,
              label: 'Gross sales',
              state: 'ready',
              value: formatMinor(totals.gross_sales_minor, currency),
            },
            {
              id: `refunds-${currency}`,
              label: 'Refunds',
              state: 'ready',
              value: formatMinor(totals.refunds_minor, currency),
            },
            {
              id: `orders-${currency}`,
              label: 'Orders',
              state: 'ready',
              value: String(totals.orders),
            },
          ]}
        />
        <SalesChart series={series} currency={currency} bucket={bucket} />
        <SalesTable series={series} currency={currency} bucket={bucket} />
        <div className="grid gap-6 lg:grid-cols-2">
          <TopProducts
            title="Top products by revenue"
            products={entry.top_products_by_revenue}
            currency={currency}
            testId={`top-revenue-${currency}`}
          />
          <TopProducts
            title="Top products by units"
            products={entry.top_products_by_units}
            currency={currency}
            testId={`top-units-${currency}`}
          />
        </div>
      </CardContent>
    </Card>
  );
}
