// @vitest-environment node
/**
 * KAN-123: server actions that serve protected data must reject an unverified user, however the
 * client-writable `email-verified` cookie is set.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  cookieJar: new Map<string, string>(),
  verifySessionCookie: vi.fn(),
  userFindUnique: vi.fn(),
  userUpdate: vi.fn(),
  notificationFindMany: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) =>
      mocks.cookieJar.has(name) ? { value: mocks.cookieJar.get(name) } : undefined,
    set: vi.fn(),
    delete: vi.fn(),
  }),
  headers: async () => new Headers(),
}));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ verifySessionCookie: mocks.verifySessionCookie }),
}));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ applyActionCode: vi.fn() }));
vi.mock('@/lib/db/client', () => ({
  db: {
    user: { findUnique: mocks.userFindUnique, update: mocks.userUpdate },
    notification: { findMany: mocks.notificationFindMany, count: vi.fn() },
    adminUser: { findUnique: vi.fn() },
  },
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/stripe/subscriptions', () => ({ cancelSubscription: vi.fn() }));
vi.mock('@/lib/utils/notifications', () => ({
  notifyPasswordChanged: vi.fn(),
  notifyNewDeviceLogin: vi.fn(),
  notifyEmailVerified: vi.fn(),
}));
vi.mock('@/lib/utils/geo-ip', () => ({ getLocationFromIP: vi.fn() }));

import { getUserProfileAction, updateUserProfileAction } from '@/app/actions/user-actions';
import { getNotificationsAction } from '@/app/actions/notification-actions';
import { getCurrentSessionAction } from '@/app/actions/auth-actions';
import { getCurrentAdmin, isAdmin } from '@/lib/helpers/admin-helpers';

const unverified = { uid: 'uid-1', email: 'a@b.test', email_verified: false };
const verified = { uid: 'uid-1', email: 'a@b.test', email_verified: true };

describe('KAN-123: protected server actions require a verified session', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieJar.clear();
    mocks.cookieJar.set('session', 'session-cookie');
    mocks.userFindUnique.mockResolvedValue({
      id: 'user-1',
      email: 'a@b.test',
      adminUser: { role: 'admin', permissions: ['*'] },
      settings: null,
    });
    mocks.notificationFindMany.mockResolvedValue([]);
  });

  describe.each([
    ['forged email-verified=true cookie', { 'email-verified': 'true' }],
    ['stale email-verified=false cookie', { 'email-verified': 'false' }],
    ['missing email-verified cookie', {}],
  ])('unverified user with a %s', (_label, extraCookies) => {
    beforeEach(() => {
      for (const [name, value] of Object.entries(extraCookies)) mocks.cookieJar.set(name, value);
      mocks.verifySessionCookie.mockResolvedValue(unverified);
    });

    it('gets no profile data', async () => {
      const result = await getUserProfileAction();

      expect(result).toMatchObject({ success: false, error: 'Unauthorized' });
      expect(mocks.userFindUnique).not.toHaveBeenCalled();
    });

    it('cannot update the profile', async () => {
      const result = await updateUserProfileAction({ displayName: 'Mallory' });

      expect(result).toMatchObject({ success: false, error: 'Unauthorized' });
      expect(mocks.userUpdate).not.toHaveBeenCalled();
    });

    it('gets no notifications', async () => {
      const result = await getNotificationsAction();

      expect(result.success).toBe(false);
      expect(mocks.notificationFindMany).not.toHaveBeenCalled();
    });

    it('gets no session data', async () => {
      const result = await getCurrentSessionAction();

      expect(result.success).toBe(false);
      expect(mocks.userFindUnique).not.toHaveBeenCalled();
    });

    it('is not an admin, even when the database says admin', async () => {
      expect(await isAdmin()).toBe(false);
      expect(await getCurrentAdmin()).toBeNull();
    });
  });

  it('rejects a revoked session', async () => {
    mocks.verifySessionCookie.mockRejectedValue(
      Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' })
    );

    expect(await getUserProfileAction()).toMatchObject({ success: false, error: 'Unauthorized' });
    expect(mocks.verifySessionCookie).toHaveBeenCalledWith('session-cookie', true);
  });

  it('rejects a request with no session cookie even with email-verified=true', async () => {
    mocks.cookieJar.clear();
    mocks.cookieJar.set('email-verified', 'true');

    expect(await getUserProfileAction()).toMatchObject({ success: false, error: 'Unauthorized' });
    expect(mocks.verifySessionCookie).not.toHaveBeenCalled();
  });

  it('serves a verified user whatever the email-verified cookie says', async () => {
    mocks.cookieJar.set('email-verified', 'false');
    mocks.verifySessionCookie.mockResolvedValue(verified);

    const result = await getUserProfileAction();

    expect(result.success).toBe(true);
  });
});
