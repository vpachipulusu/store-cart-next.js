// @vitest-environment node
/**
 * KAN-184: admin pages without a backend API show a "not available yet" state and no longer import the
 * database; the users list and detail pages read through the admin users API wrapper.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const mocks = vi.hoisted(() => ({
  fetchAdminUsers: vi.fn(),
  fetchAdminUser: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
  logError: vi.fn(),
  fetchAdminAuditLogs: vi.fn(),
  fetchAdminSubscriptions: vi.fn(),
  getStripePrices: vi.fn(),
}));

vi.mock('@/lib/api/admin-users', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/admin-users')>('@/lib/api/admin-users');
  return {
    ...actual,
    fetchAdminUsers: mocks.fetchAdminUsers,
    fetchAdminUser: mocks.fetchAdminUser,
  };
});
vi.mock('@/lib/api/admin-audit-logs', () => ({
  AUDIT_LOG_PAGE_SIZE: 100,
  fetchAdminAuditLogs: mocks.fetchAdminAuditLogs,
}));
vi.mock('@/lib/api/admin-subscriptions', () => ({
  fetchAdminSubscriptions: mocks.fetchAdminSubscriptions,
}));
vi.mock('@/config/subscriptions', () => ({
  getStripePrices: mocks.getStripePrices,
  getCurrencySymbol: vi.fn(async () => '$'),
}));
vi.mock('@/components/admin/refresh-button', () => ({ RefreshButton: () => <span /> }));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/app/(admin)/admin/users/user-row-actions', () => ({
  UserRowActions: ({ userId }: { userId: string }) => <span data-row-actions={userId} />,
}));

import type { AuditLogEntry, SubscriptionSummary } from '@/lib/api/generated';
import AdminDashboardPage from '@/app/(admin)/admin/page';
import AdminAnalyticsPage from '@/app/(admin)/admin/analytics/page';
import AdminSeoPage from '@/app/(admin)/admin/seo/page';
import AdminSettingsPage from '@/app/(admin)/admin/settings/page';
import AdminAuditLogsPage from '@/app/(admin)/admin/audit-logs/page';
import AdminSubscriptionsPage from '@/app/(admin)/admin/subscriptions/page';
import AdminUserDetailPage from '@/app/(admin)/admin/users/[id]/page';

const ADMIN_DIR = join(process.cwd(), 'src/app/(admin)/admin');
const html = (node: React.ReactNode) => renderToStaticMarkup(node as React.ReactElement);

const SUMMARY = {
  id: 'user-1',
  email: 'ada@example.test',
  email_verified: true,
  display_name: 'Ada',
  avatar_url: null,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
  is_admin: true,
  admin_role: 'super_admin',
};

describe('switched-off admin pages', () => {
  it.each([
    ['dashboard', AdminDashboardPage],
    ['analytics', AdminAnalyticsPage],
    ['seo', AdminSeoPage],
    ['settings', AdminSettingsPage],
  ])('%s shows the not available state', (_name, Page) => {
    expect(html(<Page />)).toContain('Not available yet');
  });

  it.each([
    'page.tsx',
    'analytics/page.tsx',
    'seo/page.tsx',
    'settings/page.tsx',
    'users/page.tsx',
    'users/[id]/page.tsx',
    'audit-logs/page.tsx',
    'subscriptions/page.tsx',
  ])('%s does not import the database client', (file) => {
    expect(readFileSync(join(ADMIN_DIR, file), 'utf8')).not.toContain('@/lib/db/client');
  });
});

describe('admin user detail page', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the user read through the API', async () => {
    mocks.fetchAdminUser.mockResolvedValue({
      success: true,
      data: {
        ...SUMMARY,
        bio: 'Mathematician',
        location: null,
        website: null,
        phone_number: null,
        two_factor_enabled: true,
        admin_permissions: ['users.read'],
      },
    });

    const markup = html(await AdminUserDetailPage({ params: Promise.resolve({ id: 'user-1' }) }));

    expect(mocks.fetchAdminUser).toHaveBeenCalledWith('user-1');
    expect(markup).toContain('ada@example.test');
    expect(markup).toContain('Mathematician');
    expect(markup).toContain('users.read');
  });

  it('shows status pills and one h1, with a retry link on the error state', async () => {
    mocks.fetchAdminUser.mockResolvedValue({
      success: true,
      data: {
        ...SUMMARY,
        email_verified: false,
        bio: null,
        location: null,
        website: null,
        phone_number: null,
        two_factor_enabled: false,
        admin_permissions: ['users.read'],
      },
    });

    const markup = html(await AdminUserDetailPage({ params: Promise.resolve({ id: 'user-1' }) }));

    expect(markup).toContain('Unverified');
    expect(markup).toContain('bg-warn');
    expect(markup).toContain('bg-info');
    expect(markup).toContain('Basic Information');
    expect(markup).toContain('Admin Access');
    expect(markup.match(/<h1/g)).toHaveLength(1);

    mocks.fetchAdminUser.mockResolvedValue({ success: false, error: 'x', status: 500 });
    const failed = html(await AdminUserDetailPage({ params: Promise.resolve({ id: 'a b' }) }));
    expect(failed.match(/<h1/g)).toHaveLength(1);
    expect(failed).toContain('href="/admin/users/a%20b"');
    expect(failed).toContain('Back to Users');
    expect(failed).toContain('role="alert"');
    expect(failed).toContain('>Retry<');
  });

  it('shows good pills for a verified user with 2FA and None for a non-admin', async () => {
    mocks.fetchAdminUser.mockResolvedValue({
      success: true,
      data: {
        ...SUMMARY,
        is_admin: false,
        admin_role: null,
        bio: null,
        location: null,
        website: null,
        phone_number: null,
        two_factor_enabled: true,
        admin_permissions: [],
      },
    });

    const markup = html(await AdminUserDetailPage({ params: Promise.resolve({ id: 'user-1' }) }));

    expect(markup).toContain('Verified');
    expect(markup).toContain('Enabled');
    expect(markup).toContain('bg-good');
    expect(markup).not.toContain('bg-warn');
    expect(markup).toContain('None');
    expect(markup).not.toContain('Permissions');
  });

  it('renders the unavailable state as one panel with a way back', () => {
    const markup = html(<AdminSeoPage />);

    expect(markup.match(/<h1/g)).toHaveLength(1);
    expect(markup.match(/<section/g)).toHaveLength(1);
    expect(markup).toContain('href="/admin/users"');
  });

  it('calls notFound for a missing user', async () => {
    mocks.fetchAdminUser.mockResolvedValue({ success: false, error: 'x', status: 404 });

    await expect(
      AdminUserDetailPage({ params: Promise.resolve({ id: 'missing' }) })
    ).rejects.toThrow('NEXT_NOT_FOUND');
  });

  it('shows a curated error for other failures', async () => {
    mocks.fetchAdminUser.mockResolvedValue({ success: false, error: 'SECRET', status: 500 });

    const markup = html(await AdminUserDetailPage({ params: Promise.resolve({ id: 'u1' }) }));

    expect(markup).toContain('Something went wrong');
    expect(markup).not.toContain('SECRET');
  });
});

const ENTRY = {
  id: 'a1',
  created_at: '2026-01-01T00:00:00Z',
  user_id: 'user-1',
  organization_id: null,
  store_id: null,
  action: 'user.ban',
  resource: 'user',
  resource_id: null,
  metadata: null,
  ip_address: '203.0.113.9',
  user_agent: null,
} satisfies AuditLogEntry;

const auditPage = (entries: AuditLogEntry[], total = entries.length) => ({
  success: true,
  data: { entries, total_count: total, limit: 100, offset: 0 },
});

describe('admin audit logs page', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders entries read through the API with a labelled table and the total', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue(auditPage([ENTRY], 250));

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toContain('user.ban');
    expect(markup).toContain('user-1');
    expect(markup).toContain('203.0.113.9');
    expect(markup).toContain('Showing 1 of 250 entries');
    expect(markup).toContain('aria-label="Audit log entries"');
  });

  it('labels timestamps as UTC and leaves an unparsable one empty', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue(
      auditPage([
        { ...ENTRY, id: 'a', created_at: '2026-01-05T14:03:00Z' },
        { ...ENTRY, id: 'b', created_at: 'garbage' },
      ])
    );

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toContain('5 Jan 2026, 14:03 UTC');
    expect(markup).not.toContain('Invalid Date');
  });

  it('gives screen readers text for missing user and IP values', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue(
      auditPage([{ ...ENTRY, user_id: null, ip_address: null } satisfies AuditLogEntry])
    );

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toContain('<span class="sr-only">None</span>');
  });

  it('shows the empty state when there are no entries', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue(auditPage([]));

    expect(html(await AdminAuditLogsPage())).toContain('No audit logs found');
  });

  it('renders a stacked table with a labelled cell per column', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue(auditPage([ENTRY]));

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toContain('role="table"');
    for (const label of ['Timestamp', 'Action', 'Resource', 'User ID', 'IP Address']) {
      expect(markup).toContain(`data-label="${label}"`);
    }
  });

  it('shows an inline error with a Retry link back to the page', async () => {
    mocks.fetchAdminAuditLogs.mockResolvedValue({ success: false, error: 'SECRET', status: 500 });

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toMatch(/<a[^>]*href="\/admin\/audit-logs"[^>]*>Retry<\/a>/);
    expect(markup).not.toContain('<table');
  });

  it.each([
    [403, 'You do not have permission to do that'],
    [404, 'Not found'],
    [500, 'Something went wrong'],
    [undefined, 'The admin service is unavailable'],
  ])('shows a curated message for status %s and no backend text', async (status, text) => {
    mocks.fetchAdminAuditLogs.mockResolvedValue({ success: false, error: 'SECRET', status });

    const markup = html(await AdminAuditLogsPage());

    expect(markup).toContain(text);
    expect(markup).not.toContain('SECRET');
    expect(markup).not.toContain('User not found');
    expect(markup).toContain('role="alert"');
    expect(mocks.logError).toHaveBeenCalled();
  });
});

describe('admin subscriptions page', () => {
  const sub = (id: string, plan: SubscriptionSummary['plan'], createdAt: string) =>
    ({
      organization_id: id,
      name: `Org ${id}`,
      slug: `org-${id}`,
      plan,
      status: 'active',
      current_period_end: null,
      cancel_at_period_end: false,
      has_stripe_subscription: false,
      granted_plan: null,
      granted_until: null,
      created_at: createdAt,
    }) satisfies SubscriptionSummary;
  type Query = { status?: string; plan?: string };
  const page = (subscriptions: SubscriptionSummary[], total = subscriptions.length) => ({
    success: true,
    data: { subscriptions, total_count: total, limit: 20, offset: 0 },
  });
  const byQuery = (q: Query) => {
    if (q.status === 'canceled') return page([], 4);
    if (q.plan === 'pro') return page([sub('p1', 'pro', '2026-01-02T00:00:00Z')], 3);
    return page([sub('e1', 'enterprise', '2026-01-03T00:00:00Z')], 2);
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getStripePrices.mockResolvedValue({ pro: { monthly: 10 }, enterprise: { monthly: 100 } });
    mocks.fetchAdminSubscriptions.mockImplementation(async (q: Query) => byQuery(q));
  });

  it('computes the counts and MRR from the API totals and lists the newest organisations', async () => {
    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('Newest paid organisations');
    expect(markup.indexOf('Org e1')).toBeLessThan(markup.indexOf('Org p1'));
    expect(markup).toContain('$230');
    expect(markup).toContain('4 canceled (all time)');
    expect(mocks.fetchAdminSubscriptions).toHaveBeenCalledWith({
      status: 'active',
      plan: 'pro',
      limit: 20,
    });
    expect(mocks.fetchAdminSubscriptions).toHaveBeenCalledWith({
      status: 'active',
      plan: 'enterprise',
      limit: 20,
    });
  });

  it('orders by the parsed timestamp, not the string', async () => {
    mocks.fetchAdminSubscriptions.mockImplementation(async (q: Query) =>
      q.plan === 'pro'
        ? page([sub('p1', 'pro', '2026-01-02T10:00:00+02:00')])
        : q.plan === 'enterprise'
          ? page([sub('e1', 'enterprise', '2026-01-02T09:00:00Z')])
          : page([])
    );

    const markup = html(await AdminSubscriptionsPage());

    // 10:00+02:00 is 08:00Z, so the enterprise org (09:00Z) is newer although its string sorts lower.
    expect(markup.indexOf('Org e1')).toBeLessThan(markup.indexOf('Org p1'));
  });

  it('keeps only the newest 20 across both plans', async () => {
    const many = (plan: 'pro' | 'enterprise', day: number) =>
      Array.from({ length: 20 }, (_, i) =>
        sub(
          `${plan}-${i}`,
          plan,
          `2026-01-${String(day).padStart(2, '0')}T00:${String(i).padStart(2, '0')}:00Z`
        )
      );
    mocks.fetchAdminSubscriptions.mockImplementation(async (q: Query) =>
      q.plan === 'pro'
        ? page(many('pro', 5), 20)
        : q.plan === 'enterprise'
          ? page(many('enterprise', 4), 20)
          : page([])
    );

    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('Org pro-0');
    expect(markup).not.toContain('Org enterprise-0');
  });

  it('labels the table and the manage buttons, and gives empty renewal dates text', async () => {
    const markup = html(await AdminSubscriptionsPage());

    for (const header of ['Organisation', 'Slug', 'Plan', 'Status', 'Renewal Date']) {
      expect(markup).toContain(`>${header}</th>`);
    }
    expect(markup).toContain('aria-label="Newest paid organisations"');
    expect(markup).toContain('aria-label="Manage Org p1"');
    expect(markup).toContain('<span class="sr-only">None</span>');
  });

  it('shows the counts and MRR in a key figures strip', async () => {
    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('aria-label="Key figures"');
    for (const label of ['Total active', 'Pro plans', 'Enterprise plans', 'MRR']) {
      expect(markup).toContain(`aria-label="${label}"`);
    }
    expect(markup).toMatch(/aria-label="Total active"[^]*?>5<\/p>/);
    expect(markup).toContain('$10/month each');
    expect(markup).toContain('$100/month each');
  });

  it('marks a missing price in the strip without hiding the counts', async () => {
    mocks.getStripePrices.mockRejectedValue(new Error('prices down'));

    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('Price unavailable');
    expect(markup).toMatch(/aria-label="MRR"[^]*?Price unavailable/);
    expect(markup).not.toMatch(/aria-label="MRR"[^]*?\$\d/);
  });

  it('shows plan and status as pills in a stacked table', async () => {
    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('role="table"');
    expect(markup).toContain('data-label="Plan"');
    expect(markup).toContain('data-label="Status"');
    expect(markup).toMatch(/rounded-full[^>]*>(<svg.*?<\/svg>)?Enterprise<\/span>/);
    expect(markup).toMatch(/rounded-full[^>]*>(<svg.*?<\/svg>)?Active<\/span>/);
  });

  it('shows a non-active status as a warning pill', async () => {
    mocks.fetchAdminSubscriptions.mockImplementation(async (q: Query) =>
      q.plan === 'pro'
        ? page([{ ...sub('p1', 'pro', '2026-01-02T00:00:00Z'), status: 'past_due' }])
        : page([])
    );

    expect(html(await AdminSubscriptionsPage())).toMatch(/bg-warn[^>]*>(<svg.*?<\/svg>)?Past due/);
  });

  it('shows the empty state when no paid organisation exists', async () => {
    mocks.fetchAdminSubscriptions.mockImplementation(async () => page([]));

    expect(html(await AdminSubscriptionsPage())).toContain('No Active Subscriptions');
  });

  it('still renders counts and the table when the price read fails', async () => {
    mocks.getStripePrices.mockRejectedValue(new Error('prices down'));

    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('Org p1');
    expect(markup).toContain('Price unavailable');
    expect(mocks.logError).toHaveBeenCalled();
  });

  it.each([
    ['canceled', { status: 'canceled' }],
    ['pro', { plan: 'pro' }],
    ['enterprise', { plan: 'enterprise' }],
  ])('shows a curated error when the %s call fails', async (_name, match) => {
    mocks.fetchAdminSubscriptions.mockImplementation(async (q: Query) =>
      Object.entries(match).every(([k, v]) => (q as Record<string, unknown>)[k] === v)
        ? { success: false, error: 'SECRET', status: 404 }
        : byQuery(q)
    );

    const markup = html(await AdminSubscriptionsPage());

    expect(markup).toContain('Not found');
    expect(markup).not.toContain('User not found');
    expect(markup).not.toContain('SECRET');
    expect(markup).not.toContain('Newest paid organisations');
    expect(markup).toContain('role="alert"');
    expect(markup).toMatch(/<a[^>]*href="\/admin\/subscriptions"[^>]*>Retry<\/a>/);
    expect(mocks.logError).toHaveBeenCalled();
  });
});
