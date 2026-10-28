import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { BUCKET_LABELS, formatBucketLabel, type AnalyticsBucket } from '@/lib/analytics/query';
import { formatMinor } from '@/lib/products/money';
import type { SalesPointData } from '@/lib/api/analytics';

/** Every bucket of the range, empty ones included: the accessible form of the sales chart. */
export function SalesTable({
  series,
  currency,
  bucket,
}: {
  series: ReadonlyArray<SalesPointData>;
  currency: string;
  bucket: AnalyticsBucket;
}) {
  return (
    <Table stacked data-testid={`sales-table-${currency}`}>
      <TableCaption>{`${BUCKET_LABELS[bucket]} sales in ${currency}`}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Period</TableHead>
          <TableHead numeric>Orders</TableHead>
          <TableHead numeric>Gross sales</TableHead>
          <TableHead numeric>Refunds</TableHead>
          <TableHead numeric>Net sales</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {series.map((point) => (
          <TableRow key={point.bucket_start} data-testid="sales-row">
            <TableCell className="font-medium">
              {formatBucketLabel(point.bucket_start, bucket)}
            </TableCell>
            <TableCell numeric label="Orders">
              {point.orders}
            </TableCell>
            <TableCell numeric label="Gross">
              {formatMinor(point.gross_sales_minor, currency)}
            </TableCell>
            <TableCell numeric label="Refunds">
              {formatMinor(point.refunds_minor, currency)}
            </TableCell>
            <TableCell numeric label="Net">
              {formatMinor(point.net_sales_minor, currency)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
