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
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/app/(admin)/admin/users/user-row-actions', () => ({
  UserRowActions: ({ userId }: { userId: string }) => <span data-row-actions={userId} />,
}));

import AdminDashboardPage from '@/app/(admin)/admin/page';
import AdminAnalyticsPage from '@/app/(admin)/admin/analytics/page';
import AdminSeoPage from '@/app/(admin)/admin/seo/page';
import AdminSettingsPage from '@/app/(admin)/admin/settings/page';
import AdminUsersPage from '@/app/(admin)/admin/users/page';
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
  ])('%s does not import the database client', (file) => {
    expect(readFileSync(join(ADMIN_DIR, file), 'utf8')).not.toContain('@/lib/db/client');
  });
});

describe('admin users list page', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders users from the API and passes search and paging through', async () => {
    mocks.fetchAdminUsers.mockResolvedValue({
      success: true,
      data: { users: [SUMMARY], total_count: 120, limit: 50, offset: 50 },
    });

    const markup = html(
      await AdminUsersPage({ searchParams: Promise.resolve({ q: 'ada', page: '2' }) })
    );

    expect(mocks.fetchAdminUsers).toHaveBeenCalledWith({ search: 'ada', limit: 50, offset: 50 });
    expect(markup).toContain('ada@example.test');
    expect(markup).toContain('super admin');
    expect(markup).toContain('data-row-actions="user-1"');
    expect(markup).toContain('All Users (120)');
    expect(markup).toContain('/admin/users?q=ada');
    expect(markup).toContain('/admin/users?q=ada&amp;page=3');
  });

  it('shows a curated error and no backend text when the API fails', async () => {
    mocks.fetchAdminUsers.mockResolvedValue({
      success: false,
      error: 'SECRET postgres://user:pw@host/db',
      status: 403,
    });

    const markup = html(await AdminUsersPage({ searchParams: Promise.resolve({}) }));

    expect(markup).toContain('You do not have permission to do that');
    expect(markup).not.toContain('SECRET');
  });

  it('treats a non-numeric page as page 1', async () => {
    mocks.fetchAdminUsers.mockResolvedValue({
      success: true,
      data: { users: [], total_count: 0, limit: 50, offset: 0 },
    });

    await AdminUsersPage({ searchParams: Promise.resolve({ page: 'abc' }) });

    expect(mocks.fetchAdminUsers.mock.calls[0][0].offset).toBe(0);
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
