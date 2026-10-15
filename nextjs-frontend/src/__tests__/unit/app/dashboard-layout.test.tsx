// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DB_DOWN,
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
  fetchMerchantStores: vi.fn(),
}));

vi.mock('next/navigation', () => navigationMock);
vi.mock('next/headers', () => ({ cookies: async () => ({ get: mocks.cookieGet }) }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/api/account', () => ({ fetchProfile: mocks.fetchProfile }));
vi.mock('@/lib/api/stores', () => ({ fetchMerchantStores: mocks.fetchMerchantStores }));
vi.mock('@/lib/logger', () => ({ logger: { error: mocks.loggerError } }));
vi.mock('@/components/providers/session-provider', () => ({ SessionProvider: () => null }));
vi.mock('@/components/dashboard/dashboard-header', () => ({ DashboardHeader: () => null }));
vi.mock('@/components/dashboard/store-switcher', () => ({ StoreSwitcher: () => null }));

import DashboardLayout from '@/app/dashboard/layout';
import { StoreSwitcher } from '@/components/dashboard/store-switcher';

/** Finds the props.user handed to DashboardHeader in the rendered element tree. */
function findHeaderUser(node: unknown): Record<string, unknown> | undefined {
  if (!node || typeof node !== 'object') return undefined;
  const element = node as { props?: { user?: Record<string, unknown>; children?: unknown } };
  if (element.props?.user && 'dbDisplayName' in element.props.user) return element.props.user;
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const found = findHeaderUser(child);
    if (found) return found;
  }
  return undefined;
}

/** True when any element in the rendered tree carries the given prop value. */
function hasProp(node: unknown, prop: string, value: unknown): boolean {
  if (!node || typeof node !== 'object') return false;
  const props = (node as { props?: Record<string, unknown> }).props;
  if (props?.[prop] === value) return true;
  const children = props?.children;
  return (Array.isArray(children) ? children : [children]).some((child) =>
    hasProp(child, prop, value)
  );
}

/** True when the tree contains an element of the given component type. */
function hasType(node: unknown, type: unknown): boolean {
  if (!node || typeof node !== 'object') return false;
  const element = node as { type?: unknown; props?: { children?: unknown } };
  if (element.type === type) return true;
  const children = element.props?.children;
  return (Array.isArray(children) ? children : [children]).some((child) => hasType(child, type));
}

/** True when any string in the rendered tree contains the text. */
function hasText(node: unknown, text: string): boolean {
  if (typeof node === 'string') return node.includes(text);
  if (!node || typeof node !== 'object') return false;
  const children = (node as { props?: { children?: unknown } }).props?.children;
  return (Array.isArray(children) ? children : [children]).some((child) => hasText(child, text));
}

const STORE = {
  id: 'tz4a98xxat96iws9zmbrgj3a',
  name: 'Alpha',
  slug: 'alpha',
  status: 'ACTIVE',
  organizationId: 'org-1',
  organizationName: 'Org',
};

const OTHER_STORE = { ...STORE, id: 'pfh0haxfpzowht3oi213cqos', name: 'Beta', slug: 'beta' };

describe('DashboardLayout session check', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieGet.mockImplementation((name: string) =>
      name === 'session' ? { value: 'cookie-value' } : undefined
    );
    mocks.verifySessionCookie.mockResolvedValue({
      uid: 'uid-1',
      email: 'a@b.test',
      email_verified: true,
    });
    mocks.fetchProfile.mockResolvedValue({
      success: true,
      data: { display_name: null, avatar_url: null },
    });
    mocks.fetchMerchantStores.mockResolvedValue({ success: true, data: [STORE, OTHER_STORE] });
  });

  describe('KAN-61: store scope', () => {
    it('scopes the main area to the first store when no cookie is set and shows the switcher', async () => {
      const tree = await DashboardLayout({ children: null });

      expect(hasProp(tree, 'data-store-id', STORE.id)).toBe(true);
      expect(hasType(tree, StoreSwitcher)).toBe(true);
      expect(hasProp(tree, 'data-testid', 'no-stores')).toBe(false);
    });

    it('scopes to the store in the cookie when the user may open it', async () => {
      mocks.cookieGet.mockImplementation((name: string) =>
        name === 'session'
          ? { value: 'cookie-value' }
          : name === 'selected-store'
            ? { value: OTHER_STORE.id }
            : undefined
      );

      expect(
        hasProp(await DashboardLayout({ children: null }), 'data-store-id', OTHER_STORE.id)
      ).toBe(true);
    });

    it('ignores a cookie for a store the user cannot open', async () => {
      mocks.cookieGet.mockImplementation((name: string) =>
        name === 'session'
          ? { value: 'cookie-value' }
          : name === 'selected-store'
            ? { value: 'ckwdiixuhlkv0ib2d6m3y6hz' }
            : undefined
      );

      expect(hasProp(await DashboardLayout({ children: null }), 'data-store-id', STORE.id)).toBe(
        true
      );
    });

    it('shows the empty state, no switcher and no store scope when the user has no stores', async () => {
      mocks.fetchMerchantStores.mockResolvedValue({ success: true, data: [] });

      const tree = await DashboardLayout({ children: null });

      expect(hasProp(tree, 'data-testid', 'no-stores')).toBe(true);
      expect(hasText(tree, 'You do not have a store yet.')).toBe(true);
      expect(hasType(tree, StoreSwitcher)).toBe(false);
      expect(hasProp(tree, 'data-store-id', STORE.id)).toBe(false);
    });

    it('says the stores could not be loaded, hides the switcher and still renders the page', async () => {
      mocks.fetchMerchantStores.mockResolvedValue({ success: false, error: 'Backend unavailable' });

      const tree = await DashboardLayout({ children: 'PAGE' });

      expect(hasText(tree, 'Your stores could not be loaded')).toBe(true);
      expect(hasType(tree, StoreSwitcher)).toBe(false);
      expect(hasProp(tree, 'data-testid', 'no-stores')).toBe(false);
      expect(hasText(tree, 'PAGE')).toBe(true);
    });
  });

  it('propagates the /login redirect when there is no session cookie', async () => {
    mocks.cookieGet.mockReturnValue(undefined);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/login');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  describe('KAN-123: email-verified claim', () => {
    const unverified = { uid: 'uid-1', email: 'a@b.test', email_verified: false };
    const withCookies = (jar: Record<string, string>) =>
      mocks.cookieGet.mockImplementation((name: string) =>
        name in jar ? { value: jar[name] } : undefined
      );

    it('sends an unverified user to /verify-email', async () => {
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(error)).toBe('/verify-email');
      expect(mocks.fetchProfile).not.toHaveBeenCalled();
    });

    it('does not trust a forged email-verified=true cookie', async () => {
      withCookies({ session: 'cookie-value', 'email-verified': 'true' });
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(error)).toBe('/verify-email');
    });

    it('does not trust a missing email-verified cookie either way', async () => {
      withCookies({ session: 'cookie-value' });
      mocks.verifySessionCookie.mockResolvedValue(unverified);

      expect(redirectTarget(await rejection(DashboardLayout({ children: null })))).toBe(
        '/verify-email'
      );
    });

    it('lets a verified user through even when the cookie is stale (false)', async () => {
      withCookies({ session: 'cookie-value', 'email-verified': 'false' });

      await expect(DashboardLayout({ children: null })).resolves.toBeDefined();
      expect(navigationMock.redirect).not.toHaveBeenCalled();
    });

    it('checks revocation, and a revoked session clears the session', async () => {
      const revoked = Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' });
      mocks.verifySessionCookie.mockRejectedValue(revoked);

      const error = await rejection(DashboardLayout({ children: null }));

      expect(mocks.verifySessionCookie).toHaveBeenCalledWith('cookie-value', true);
      expect(redirectTarget(error)).toBe('/api/auth/clear-session');
    });
  });

  it('clears the session when the session cookie has expired', async () => {
    mocks.verifySessionCookie.mockRejectedValue(SESSION_EXPIRED);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(redirectTarget(error)).toBe('/api/auth/clear-session');
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('logs and rethrows a profile request error without clearing the session', async () => {
    mocks.fetchProfile.mockRejectedValue(DB_DOWN);

    const error = await rejection(DashboardLayout({ children: null }));

    expect(error).toBe(DB_DOWN);
    expect(navigationMock.redirect).not.toHaveBeenCalled();
    expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    const [, meta] = mocks.loggerError.mock.calls[0];
    expect(meta).toMatchObject({
      route: '/dashboard',
      errorName: 'Error',
      message: 'connection refused',
      userId: 'uid-1',
    });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toContain('cookie-value');
  });

  describe('KAN-41: profile comes from the API', () => {
    it('passes the API display name and avatar to the header', async () => {
      mocks.fetchProfile.mockResolvedValue({
        success: true,
        data: { display_name: 'Ada', avatar_url: 'https://x.test/a.png' },
      });

      const tree = await DashboardLayout({ children: null });

      expect(findHeaderUser(tree)).toMatchObject({
        dbDisplayName: 'Ada',
        dbAvatarUrl: 'https://x.test/a.png',
      });
    });

    it.each([
      [401, 'Invalid authentication'],
      [404, 'Not found'],
    ])('clears the session when the backend answers %s (%s)', async (status, error) => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error, status });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(redirectTarget(err)).toBe('/api/auth/clear-session');
    });

    it('does not clear the session for a 401 caused by a misconfigured internal key', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: 'Unauthorized', status: 401 });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(navigationMock.redirect).not.toHaveBeenCalled();
      expect(String(err)).toContain('Profile request failed (401)');
      expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    });

    it('rethrows when the backend is unreachable, keeping the session', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: 'Backend unavailable' });

      const err = await rejection(DashboardLayout({ children: null }));

      expect(navigationMock.redirect).not.toHaveBeenCalled();
      expect(String(err)).toContain('unreachable');
    });
  });
});
