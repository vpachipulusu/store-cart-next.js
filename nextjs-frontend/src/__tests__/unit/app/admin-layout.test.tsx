// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  REVOKED_SESSION,
  SESSION_CHECK_DOWN,
  navigationMock,
  redirectTarget,
  rejection,
} from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  fetchSessionStatus: vi.fn(),
  fetchProfile: vi.fn(),
  loggerError: vi.fn(),
  loggerWarn: vi.fn(),
  AdminHeader: () => null,
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/api/account', () => ({
  fetchProfile: mocks.fetchProfile,
  fetchSessionStatus: mocks.fetchSessionStatus,
}));
vi.mock('@/lib/logger', () => ({
  logger: { error: mocks.loggerError, warn: mocks.loggerWarn },
}));
vi.mock('@/components/admin/admin-header', () => ({ AdminHeader: mocks.AdminHeader }));

import type { ProfileData } from '@/lib/api/generated';
import AdminLayout from '@/app/(admin)/admin/layout';
import { AdminSidebar } from '@/components/admin/admin-sidebar';
import { AdminTabBar } from '@/components/admin/admin-tab-bar';

type ProfileFields = Pick<
  ProfileData,
  'id' | 'email' | 'display_name' | 'avatar_url' | 'is_admin' | 'admin_role'
>;

const profile = (overrides: Partial<ProfileFields> = {}) => ({
  success: true as const,
  data: {
    id: 'u1',
    email: 'admin@example.com',
    display_name: 'Ada',
    avatar_url: null,
    is_admin: true,
    admin_role: 'SUPER_ADMIN',
    ...overrides,
  } satisfies ProfileFields,
});

type ElementLike = { props: { children: unknown } };

function findAdminHeaderProps(node: unknown): Record<string, unknown> | null {
  if (!node || typeof node !== 'object') return null;
  const element = node as { type?: unknown; props?: Record<string, unknown> };
  if (element.type === mocks.AdminHeader) return element.props ?? null;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findAdminHeaderProps(child);
    if (found) return found;
  }
  return null;
}

function containsChild(node: unknown, needle: string): boolean {
  if (node === needle) return true;
  if (Array.isArray(node)) return node.some((child) => containsChild(child, needle));
  const props = (node as { props?: { children?: unknown } } | null)?.props;
  return typeof node === 'object' && props ? containsChild(props.children, needle) : false;
}

type TreeNode = { type?: unknown; props?: Record<string, unknown> };

function findAll(
  node: unknown,
  match: (el: TreeNode) => boolean,
  out: TreeNode[] = []
): TreeNode[] {
  if (Array.isArray(node)) {
    node.forEach((child) => findAll(child, match, out));
    return out;
  }
  if (!node || typeof node !== 'object') return out;
  const element = node as TreeNode;
  if (match(element)) out.push(element);
  findAll(element.props?.children, match, out);
  return out;
}

describe('AdminLayout access check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.fetchSessionStatus.mockResolvedValue({
      success: true,
      data: { uid: 'uid-1', email_verified: true },
    });
    mocks.fetchProfile.mockResolvedValue(profile());
  });

  it('renders the admin shell with the role from the API for an admin', async () => {
    const tree = (await AdminLayout({ children: 'page' })) as ElementLike;

    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(containsChild(tree, 'page')).toBe(true);
    expect(findAdminHeaderProps(tree)).toMatchObject({
      adminRole: 'SUPER_ADMIN',
      user: { email: 'admin@example.com', displayName: 'Ada', avatarUrl: null },
    });
  });

  it('sends a logged-in non-admin straight to /dashboard, never /login', async () => {
    mocks.fetchProfile.mockResolvedValue(profile({ is_admin: false, admin_role: null }));

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/dashboard');
    expect(navigationMock.redirect).toHaveBeenCalledTimes(1);
    expect(navigationMock.redirect).not.toHaveBeenCalledWith('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it.each([
    ['is_admin missing', { is_admin: undefined }],
    ['is_admin truthy but not true', { is_admin: 'true' }],
    ['admin without a role', { admin_role: null }],
  ])('denies access when %s', async (_name, overrides) => {
    // Deliberately malformed payloads (a string flag) that the typed fixture would reject.
    mocks.fetchProfile.mockResolvedValue(profile(overrides as Partial<ProfileFields>));

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/dashboard');
  });

  it('redirects to /login without calling the backend when there is no session cookie', async () => {
    mocks.cookieGet.mockReturnValue(undefined);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it('sends an unverified admin to /verify-email without calling the backend (KAN-123)', async () => {
    mocks.fetchSessionStatus.mockResolvedValue({
      success: true,
      data: { uid: 'uid-1', email_verified: false },
    });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/verify-email');
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it('does not log the admin out when the session check is down (fails closed, logged)', async () => {
    mocks.fetchSessionStatus.mockResolvedValue(SESSION_CHECK_DOWN);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBeNull();
    expect((error as Error).message).toBe('Session status check failed');
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it('redirects to /login when the backend reports the session revoked or expired', async () => {
    mocks.fetchSessionStatus.mockResolvedValue(REVOKED_SESSION);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it.each([
    ['401 Invalid authentication', { status: 401, error: 'Invalid authentication' }],
    ['404 no platform user', { status: 404, error: 'Not found' }],
  ])('clears the session when the backend rejects it (%s)', async (_name, failure) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, ...failure });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/api/auth/clear-session');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it.each([
    ['500 from the backend', { status: 500, error: 'Request failed' }],
    ['unreachable backend', { error: 'Backend unavailable' }],
    ['misconfigured internal key', { status: 401, error: 'Unauthorized' }],
  ])('fails closed with a logged error on %s', async (_name, failure) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, ...failure });

    const error = await rejection(AdminLayout({ children: null }));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/^Profile request failed \(/);
    expect(redirectTarget(error)).toBeNull();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({ route: '/admin', userId: 'uid-1' });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });

  it('fails closed when the profile call throws', async () => {
    mocks.fetchProfile.mockRejectedValue(new Error('boom'));

    const error = await rejection(AdminLayout({ children: null }));

    expect((error as Error).message).toBe('boom');
    expect(redirectTarget(error)).toBeNull();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
  });

  it('renders the KAN-230 shell: skip link, sidebar, tab bar and a focusable main landmark', async () => {
    const tree = await AdminLayout({ children: 'page' });

    expect(findAll(tree, (el) => el.type === AdminSidebar)).toHaveLength(1);
    expect(findAll(tree, (el) => el.type === AdminTabBar)).toHaveLength(1);
    const skip = findAll(tree, (el) => el.type === 'a');
    expect(skip.map((el) => el.props?.href)).toContain('#main-content');
    const [main] = findAll(tree, (el) => el.type === 'main');
    expect(main.props).toMatchObject({ id: 'main-content', tabIndex: -1 });
    expect(containsChild(main, 'page')).toBe(true);
  });

  it('does not render the shell for a denied user', async () => {
    mocks.fetchProfile.mockResolvedValue(profile({ is_admin: false, admin_role: null }));

    const error = await rejection(AdminLayout({ children: 'page' }));

    expect(redirectTarget(error)).toBe('/dashboard');
  });
});
