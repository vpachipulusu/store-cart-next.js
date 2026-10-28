import { barPercentages, formatBucketLabel, type AnalyticsBucket } from '@/lib/analytics/query';
import { formatMinor } from '@/lib/products/money';
import type { SalesPointData } from '@/lib/api/analytics';

/**
 * Net sales per bucket as plain CSS bars (KAN-96). The bars are decorative: the same numbers are in the sales
 * table next to it, so the chart is hidden from assistive technology and only names what it shows.
 */
export function SalesChart({
  series,
  currency,
  bucket,
}: {
  series: ReadonlyArray<SalesPointData>;
  currency: string;
  bucket: AnalyticsBucket;
}) {
  const heights = barPercentages(series.map((point) => point.net_sales_minor));
  const first = series[0];
  const last = series[series.length - 1];

  return (
    <figure className="space-y-2">
      <figcaption className="text-sm font-medium">Net sales ({currency})</figcaption>
      <div
        aria-hidden="true"
        data-testid={`sales-chart-${currency}`}
        className="flex h-40 items-end gap-px border-b border-border"
      >
        {series.map((point, index) => (
          <div
            key={point.bucket_start}
            data-testid="sales-bar"
            title={`${formatBucketLabel(point.bucket_start, bucket)}: ${formatMinor(point.net_sales_minor, currency)}`}
            className="min-w-0 flex-1 rounded-t-sm bg-primary"
            style={{ height: `${heights[index]}%` }}
          />
        ))}
      </div>
      {first && last ? (
        <div aria-hidden="true" className="flex justify-between text-xs text-muted-foreground">
          <span>{formatBucketLabel(first.bucket_start, bucket)}</span>
          {last !== first ? <span>{formatBucketLabel(last.bucket_start, bucket)}</span> : null}
        </div>
      ) : null}
    </figure>
  );
}
