// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SESSION_EXPIRED,
  navigationMock,
  redirectTarget,
  rejection,
} from './route-test-helpers';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  verifySessionCookie: vi.fn(),
  fetchProfile: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/api/account', () => ({ fetchProfile: mocks.fetchProfile }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/admin/admin-header', () => ({ AdminHeader: () => null }));

import AdminLayout from '@/app/(admin)/admin/layout';

const profile = (overrides: Record<string, unknown> = {}) => ({
  success: true as const,
  data: {
    id: 'u1',
    email: 'admin@example.com',
    display_name: 'Ada',
    avatar_url: null,
    is_admin: true,
    admin_role: 'SUPER_ADMIN',
    ...overrides,
  },
});

type ElementLike = { props: { children: unknown } };

function findAdminHeaderProps(node: unknown): Record<string, unknown> | null {
  if (!node || typeof node !== 'object') return null;
  const element = node as { type?: unknown; props?: { children?: unknown } };
  const props = element.props as Record<string, unknown> | undefined;
  if (props && 'adminRole' in props) return props;
  const children = props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findAdminHeaderProps(child);
    if (found) return found;
  }
  return null;
}

describe('AdminLayout access check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockReturnValue({ value: 'cookie-value' });
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: true });
    mocks.fetchProfile.mockResolvedValue(profile());
  });

  it('renders the admin shell with the role from the API for an admin', async () => {
    const tree = (await AdminLayout({ children: 'page' })) as ElementLike;

    expect(navigationMock.redirect).not.toHaveBeenCalled();
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
  });

  it.each([
    ['is_admin missing', { is_admin: undefined }],
    ['is_admin truthy but not true', { is_admin: 'true' }],
    ['admin without a role', { admin_role: null }],
  ])('denies access when %s', async (_name, overrides) => {
    mocks.fetchProfile.mockResolvedValue(profile(overrides));

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
    mocks.verifySessionCookie.mockResolvedValue({ uid: 'uid-1', email_verified: false });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/verify-email');
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it('redirects to /login when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
    expect(mocks.fetchProfile).not.toHaveBeenCalled();
  });

  it.each([
    ['401 Invalid authentication', { status: 401, error: 'Invalid authentication' }],
    ['404 no platform user', { status: 404, error: 'Not found' }],
  ])('redirects to /login when the backend rejects the session (%s)', async (_name, failure) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, ...failure });

    const error = await rejection(AdminLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
  });

  it.each([
    ['500 from the backend', { status: 500, error: 'Request failed' }],
    ['unreachable backend', { error: 'Backend unavailable' }],
    ['misconfigured internal key', { status: 401, error: 'Unauthorized' }],
  ])('fails closed with a logged error on %s', async (_name, failure) => {
    mocks.fetchProfile.mockResolvedValue({ success: false, ...failure });

    const error = await rejection(AdminLayout({ children: null }));

    expect(error).toBeInstanceOf(Error);
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
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
  });
});
