// @vitest-environment node
/**
 * KAN-119: the admin analytics and settings pages read the analytics API, show curated errors with a retry
 * link, and format money from minor units in the platform currency.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

const mocks = vi.hoisted(() => ({
  fetchAdminOverview: vi.fn(),
  fetchAdminRevenue: vi.fn(),
  fetchAdminSystemStats: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/admin-analytics', () => ({
  fetchAdminOverview: mocks.fetchAdminOverview,
  fetchAdminRevenue: mocks.fetchAdminRevenue,
  fetchAdminSystemStats: mocks.fetchAdminSystemStats,
}));
vi.mock('@/components/admin/refresh-button', () => ({ RefreshButton: () => <span /> }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));

import AdminAnalyticsPage from '@/app/(admin)/admin/analytics/page';
import AdminSettingsPage from '@/app/(admin)/admin/settings/page';
import { formatMinorUnits } from '@/app/(admin)/admin/_components/format-money';

const html = (node: React.ReactNode) => renderToStaticMarkup(node as React.ReactElement);
const ok = <T,>(data: T) => ({ success: true as const, data });
const fail = (status: number) => ({ success: false as const, error: 'SECRET detail', status });

const OVERVIEW = {
  users: { total: 1200, verified: 900, new_this_month: 30, active_last_30_days: 410, admins: 3 },
  organizations: { total: 80, new_this_month: 5 },
  stores_by_status: { ACTIVE: 70, FAILED: 2 },
};
const REVENUE = {
  currency: 'GBP',
  mrr_minor: 123456,
  arr_minor: 1481472,
  billed_organizations: 40,
  unpriced_organizations: 0,
  complete: true,
  by_plan: [{ plan: 'pro', organizations: 38, mrr_minor: 110000 }],
  organizations_by_status: { active: 38, past_due: 2 },
  organizations_by_tier: { pro: 38 },
  cancelling_at_period_end: 4,
  active_grants: 1,
};

describe('formatMinorUnits', () => {
  it.each([
    [123456, 'USD', '$1,234.56'],
    [123456, 'GBP', '£1,234.56'],
    [1234, 'JPY', '¥1,234'],
  ])('formats %s %s as %s', (amount, currency, expected) => {
    expect(formatMinorUnits(amount, currency)).toBe(expected);
  });

  it('falls back to the raw amount for an unknown currency code', () => {
    expect(formatMinorUnits(500, 'not-a-code')).toBe('500 not-a-code');
  });
});

describe('admin analytics page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchAdminOverview.mockResolvedValue(ok(OVERVIEW));
    mocks.fetchAdminRevenue.mockResolvedValue(ok(REVENUE));
  });

  it('shows users, organisations, stores and revenue in the platform currency', async () => {
    const markup = html(await AdminAnalyticsPage());

    expect(markup).toContain('>Analytics</h1>');
    for (const label of ['Users', 'Active, 30 days', 'Organisations', 'MRR', 'ARR']) {
      expect(markup).toContain(`aria-label="${label}"`);
    }
    expect(markup).toContain('1,200');
    expect(markup).toContain('£1,234.56');
    expect(markup).toContain('£14,814.72');
    expect(markup).toContain('pro (38)');
    expect(markup).not.toContain('could not be priced');
  });

  it('says revenue is a minimum when organisations could not be priced', async () => {
    mocks.fetchAdminRevenue.mockResolvedValue(
      ok({ ...REVENUE, complete: false, unpriced_organizations: 2 })
    );

    expect(html(await AdminAnalyticsPage())).toContain(
      '2 paying organisation(s) could not be priced'
    );
  });

  it('shows empty states when nothing is paying or provisioned', async () => {
    mocks.fetchAdminOverview.mockResolvedValue(ok({ ...OVERVIEW, stores_by_status: {} }));
    mocks.fetchAdminRevenue.mockResolvedValue(ok({ ...REVENUE, by_plan: [] }));

    const markup = html(await AdminAnalyticsPage());

    expect(markup).toContain('None yet');
    expect(markup).toContain('No paying organisations yet');
  });

  it('keeps the revenue section when the overview fails, with a curated message and retry', async () => {
    mocks.fetchAdminOverview.mockResolvedValue(fail(403));

    const markup = html(await AdminAnalyticsPage());

    expect(markup).toContain('You do not have permission to do that');
    expect(markup).not.toContain('SECRET');
    expect(markup).toMatch(/<a[^>]*href="\/admin\/analytics"[^>]*>Retry<\/a>/);
    expect(markup).toContain('£1,234.56');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it('keeps the overview when revenue fails', async () => {
    mocks.fetchAdminRevenue.mockResolvedValue(fail(502));

    const markup = html(await AdminAnalyticsPage());

    expect(markup).toContain('Something went wrong');
    expect(markup).toContain('1,200');
    expect(markup).not.toContain('aria-label="MRR"');
  });
});

describe('admin settings page', () => {
  const STATS = {
    app_settings: 4,
    feature_flags: 2,
    email_templates: 1,
    seo_entries: 0,
    redirects: 7,
    audit_logs: 1500,
    stripe_events: 90,
    admin_users: 3,
  };

  beforeEach(() => vi.clearAllMocks());

  it('lists the system counts', async () => {
    mocks.fetchAdminSystemStats.mockResolvedValue(ok(STATS));

    const markup = html(await AdminSettingsPage());

    expect(markup).toContain('>Settings</h1>');
    expect(markup).toContain('System stats');
    expect(markup).toContain('Audit log entries');
    expect(markup).toContain('1,500');
    expect(markup).toContain('Platform admins');
  });

  it('shows a curated error and a retry link when the stats fail', async () => {
    mocks.fetchAdminSystemStats.mockResolvedValue(fail(500));

    const markup = html(await AdminSettingsPage());

    expect(markup).not.toContain('SECRET');
    expect(markup).toContain('role="alert"');
    expect(markup).toMatch(/<a[^>]*href="\/admin\/settings"[^>]*>Retry<\/a>/);
    expect(mocks.logError).toHaveBeenCalled();
  });
});
