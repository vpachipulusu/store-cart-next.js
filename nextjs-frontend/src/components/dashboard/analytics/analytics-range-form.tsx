import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ANALYTICS_BUCKETS, BUCKET_LABELS, type AnalyticsBucket } from '@/lib/analytics/query';

const SELECT_CLASS =
  'h-11 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

/**
 * The range and bucket picker. A plain GET form: the choice lives in the search params and the server renders the
 * result, so it works without client JavaScript. Dates are UTC days.
 */
export function AnalyticsRangeForm({
  from,
  to,
  bucket,
}: {
  from: string;
  to: string;
  bucket: AnalyticsBucket;
}) {
  return (
    <form
      action="/dashboard/analytics"
      method="get"
      aria-label="Analytics range"
      className="flex flex-wrap items-end gap-3"
    >
      <div>
        <label htmlFor="analytics-from" className="mb-1 block text-sm font-medium">
          From
        </label>
        <Input id="analytics-from" name="from" type="date" defaultValue={from} required />
      </div>
      <div>
        <label htmlFor="analytics-to" className="mb-1 block text-sm font-medium">
          To
        </label>
        <Input id="analytics-to" name="to" type="date" defaultValue={to} required />
      </div>
      <div>
        <label htmlFor="analytics-bucket" className="mb-1 block text-sm font-medium">
          Group by
        </label>
        <select id="analytics-bucket" name="bucket" defaultValue={bucket} className={SELECT_CLASS}>
          {ANALYTICS_BUCKETS.map((value) => (
            <option key={value} value={value}>
              {BUCKET_LABELS[value]}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" variant="outline">
        Apply
      </Button>
      <Button variant="ghost" asChild>
        <Link href="/dashboard/analytics">Last 30 days</Link>
      </Button>
    </form>
  );
}
