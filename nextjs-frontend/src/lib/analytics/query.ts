/**
 * Merchant analytics (KAN-96): search params, labels and chart scaling. Pure and safe for client code.
 *
 * The range and bucket live in the URL (`?from=YYYY-MM-DD&to=YYYY-MM-DD&bucket=day|week|month`). Anything
 * malformed is dropped here so the backend applies its defaults (the last 30 UTC days, daily buckets); a range the
 * backend refuses (start after end, more than 366 days) comes back as its curated 422 message.
 */

/** Shown to roles the backend refuses (STAFF): the figures are revenue data for owners and admins. */
export const ANALYTICS_FORBIDDEN_MESSAGE = 'Analytics are not available for your role.';

export const ANALYTICS_BUCKETS = ['day', 'week', 'month'] as const;
export type AnalyticsBucket = (typeof ANALYTICS_BUCKETS)[number];

export const BUCKET_LABELS: Record<AnalyticsBucket, string> = {
  day: 'Daily',
  week: 'Weekly',
  month: 'Monthly',
};

export type AnalyticsQuery = {
  from?: string;
  to?: string;
  bucket: AnalyticsBucket;
};

type Param = string | string[] | undefined;

export type AnalyticsSearchParams = { from?: Param; to?: Param; bucket?: Param };

function first(value: Param): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real calendar date written as YYYY-MM-DD (so 2026-02-30 is refused). */
export function isIsoDate(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function isAnalyticsBucket(value: unknown): value is AnalyticsBucket {
  return typeof value === 'string' && (ANALYTICS_BUCKETS as ReadonlyArray<string>).includes(value);
}

export function parseAnalyticsQuery(params: AnalyticsSearchParams): AnalyticsQuery {
  const from = first(params.from);
  const to = first(params.to);
  const bucket = first(params.bucket);
  return {
    ...(isIsoDate(from) ? { from } : {}),
    ...(isIsoDate(to) ? { to } : {}),
    bucket: isAnalyticsBucket(bucket) ? bucket : 'day',
  };
}

/** The page URL for a query; the default bucket is left out. */
export function analyticsHref(query: AnalyticsQuery): string {
  const params = new URLSearchParams();
  if (query.from) params.set('from', query.from);
  if (query.to) params.set('to', query.to);
  if (query.bucket !== 'day') params.set('bucket', query.bucket);
  const qs = params.toString();
  return qs ? `/dashboard/analytics?${qs}` : '/dashboard/analytics';
}

const DAY_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
});
const FULL_DAY_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});
const MONTH_FORMAT = new Intl.DateTimeFormat('en-GB', {
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});

function utcDate(isoDate: string): Date | null {
  if (!isIsoDate(isoDate)) return null;
  return new Date(`${isoDate}T00:00:00Z`);
}

/** "1 Oct", "Week of 28 Sep" or "Oct 2026" for a bucket's first UTC day. */
export function formatBucketLabel(isoDate: string, bucket: AnalyticsBucket): string {
  const date = utcDate(isoDate);
  if (!date) return '—';
  if (bucket === 'month') return MONTH_FORMAT.format(date);
  if (bucket === 'week') return `Week of ${DAY_FORMAT.format(date)}`;
  return DAY_FORMAT.format(date);
}

/** "1 Oct 2026 to 30 Oct 2026" for the range the backend applied. */
export function formatRange(start: string, end: string): string {
  const from = utcDate(start);
  const to = utcDate(end);
  if (!from || !to) return '—';
  return `${FULL_DAY_FORMAT.format(from)} to ${FULL_DAY_FORMAT.format(to)}`;
}

/** Bar heights as percentages of the largest value; negative values draw as 0. */
export function barPercentages(values: ReadonlyArray<number>): number[] {
  const max = Math.max(0, ...values);
  if (max === 0) return values.map(() => 0);
  return values.map((value) => (value > 0 ? (value / max) * 100 : 0));
}
