/** KAN-96: analytics search params, labels and bar scaling. */
import { describe, expect, it } from 'vitest';
import {
  analyticsHref,
  barPercentages,
  formatBucketLabel,
  formatRange,
  isIsoDate,
  parseAnalyticsQuery,
} from '@/lib/analytics/query';

describe('parseAnalyticsQuery', () => {
  it('keeps valid dates and a known bucket', () => {
    expect(parseAnalyticsQuery({ from: '2026-10-01', to: '2026-10-31', bucket: 'week' })).toEqual({
      from: '2026-10-01',
      to: '2026-10-31',
      bucket: 'week',
    });
  });

  it('drops malformed values so the backend defaults apply', () => {
    expect(parseAnalyticsQuery({ from: 'yesterday', to: '2026-02-30', bucket: 'year' })).toEqual({
      bucket: 'day',
    });
  });

  it('uses the first value of a repeated param', () => {
    expect(parseAnalyticsQuery({ from: ['2026-10-01', '2026-11-01'] }).from).toBe('2026-10-01');
  });
});

describe('isIsoDate', () => {
  it.each([
    ['2026-10-01', true],
    ['2024-02-29', true],
    ['2026-02-29', false],
    ['2026-1-01', false],
    ['2026-10-01T00:00:00Z', false],
    [20261001, false],
  ])('%s -> %s', (value, expected) => {
    expect(isIsoDate(value)).toBe(expected);
  });
});

describe('analyticsHref', () => {
  it('leaves the default bucket and missing dates out', () => {
    expect(analyticsHref({ bucket: 'day' })).toBe('/dashboard/analytics');
    expect(analyticsHref({ from: '2026-10-01', to: '2026-10-02', bucket: 'month' })).toBe(
      '/dashboard/analytics?from=2026-10-01&to=2026-10-02&bucket=month'
    );
  });
});

describe('labels', () => {
  it('names day, week and month buckets in UTC', () => {
    expect(formatBucketLabel('2026-10-01', 'day')).toBe('1 Oct');
    // ICU data decides between "Sep" and "Sept" for en-GB.
    expect(formatBucketLabel('2026-09-28', 'week')).toMatch(/^Week of 28 Sept?$/);
    expect(formatBucketLabel('2026-10-01', 'month')).toBe('Oct 2026');
    expect(formatBucketLabel('not-a-date', 'day')).toBe('—');
  });

  it('formats the applied range', () => {
    expect(formatRange('2026-09-29', '2026-10-28')).toMatch(/^29 Sept? 2026 to 28 Oct 2026$/);
    expect(formatRange('bad', '2026-10-28')).toBe('—');
  });
});

describe('barPercentages', () => {
  it('scales to the largest value', () => {
    expect(barPercentages([0, 50, 100])).toEqual([0, 50, 100]);
  });

  it('draws nothing when every bucket is empty, and never a negative bar', () => {
    expect(barPercentages([0, 0])).toEqual([0, 0]);
    expect(barPercentages([-5, 10])).toEqual([0, 100]);
    expect(barPercentages([])).toEqual([]);
  });
});
