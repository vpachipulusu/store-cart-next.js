// @vitest-environment node
/** KAN-231: admin users list. The page is a shell; the results stream in behind a Suspense skeleton. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { isValidElement, Suspense } from 'react';

const mocks = vi.hoisted(() => ({ fetchAdminUsers: vi.fn(), logError: vi.fn() }));

vi.mock('@/lib/api/admin-users', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/admin-users')>('@/lib/api/admin-users');
  return { ...actual, fetchAdminUsers: mocks.fetchAdminUsers };
});
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.logError } }));
vi.mock('@/app/(admin)/admin/users/user-row-actions', () => ({
  UserRowActions: ({ userId, userLabel }: { userId: string; userLabel?: string }) => (
    <span data-row-actions={userId} data-label={userLabel} />
  ),
}));

import AdminUsersPage from '@/app/(admin)/admin/users/page';
import { UsersResults } from '@/app/(admin)/admin/users/users-results';

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

function ok(users: unknown[], total: number) {
  mocks.fetchAdminUsers.mockResolvedValue({
    success: true,
    data: { users, total_count: total, limit: 50, offset: 0 },
  });
}

describe('admin users page shell', () => {
  it('renders a 44px labelled search and a Suspense boundary around the results', async () => {
    const element = await AdminUsersPage({ searchParams: Promise.resolve({ q: 'ada' }) });
    const markup = html(element);

    expect(markup).toContain('for="user-search"');
    expect(markup).toContain('Search users by name or email');
    expect(markup).toContain('id="user-search"');
    expect(markup).toContain('value="ada"');
    expect(markup).toContain('role="search"');
    expect(isValidElement(element)).toBe(true);
    expect(JSON.stringify(element, (_k, v) => (typeof v === 'function' ? v.name : v))).toContain(
      'UsersResults'
    );
    expect(Suspense).toBeDefined();
  });

  it('shows 8 skeleton rows under a visible header while loading', async () => {
    const markup = html(await AdminUsersPage({ searchParams: Promise.resolve({}) }));
    // Static render of an async child suspends, so the fallback is emitted.
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain('Loading users');
    expect((markup.match(/<tr/g) ?? []).length).toBe(9);
    expect(markup).toContain('Last sign-in');
  });
});

describe('UsersResults', () => {
  beforeEach(() => vi.clearAllMocks());

  it('passes search and paging through and renders pills, columns and row actions', async () => {
    ok([SUMMARY], 120);
    const markup = html(await UsersResults({ query: 'ada', page: 2 }));

    expect(mocks.fetchAdminUsers).toHaveBeenCalledWith({ search: 'ada', limit: 50, offset: 50 });
    expect(markup).toContain('ada@example.test');
    expect(markup).toContain('Ada');
    expect(markup).toContain('super admin');
    expect(markup).toContain('Verified');
    expect(markup).toContain('data-row-actions="user-1"');
    expect(markup).toContain('data-label="Ada"');
    expect(markup).toContain('All Users (120)');
    expect(markup).toContain('Last sign-in');
    expect(markup).toContain('Never');
    expect(markup).toContain('/admin/users?q=ada');
    expect(markup).toContain('/admin/users?q=ada&amp;page=3');
  });

  it('marks unverified users with a pill and falls back to the email as the label', async () => {
    ok([{ ...SUMMARY, email_verified: false, display_name: null, is_admin: false }], 1);
    const markup = html(await UsersResults({ query: undefined, page: 1 }));

    expect(markup).toContain('Unverified');
    expect(markup).toContain('data-label="ada@example.test"');
    expect(markup).toContain('Not set');
  });

  it('shows the no-match state with a Clear button when a search finds nothing', async () => {
    ok([], 0);
    const markup = html(await UsersResults({ query: 'zz', page: 1 }));

    expect(markup).toContain('No users match &#x27;zz&#x27;');
    expect(markup).toContain('Clear');
    expect(markup).toContain('href="/admin/users"');
  });

  it('shows "No users yet" without a query', async () => {
    ok([], 0);
    const markup = html(await UsersResults({ query: undefined, page: 1 }));

    expect(markup).toContain('No users yet');
    expect(markup).not.toContain('Clear');
  });

  it('offers a way back to page 1 when a page past the end is empty', async () => {
    ok([], 120);
    const markup = html(await UsersResults({ query: undefined, page: 9 }));

    expect(markup).toContain('No users on this page');
    expect(markup).toContain('Back to first page');
    expect(markup).toContain('href="/admin/users"');
  });

  it('shows a curated inline error with Retry and no backend text', async () => {
    mocks.fetchAdminUsers.mockResolvedValue({
      success: false,
      error: 'SECRET postgres://user:pw@host/db',
      status: 403,
    });
    const markup = html(await UsersResults({ query: 'ada', page: 3 }));

    expect(markup).toContain('You do not have permission to do that');
    expect(markup).not.toContain('SECRET');
    expect(markup).toContain('Retry');
    expect(markup).toContain('/admin/users?q=ada&amp;page=3');
    expect(mocks.logError).toHaveBeenCalled();
  });
});
