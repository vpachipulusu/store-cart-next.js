// @vitest-environment node
/**
 * Regression tests for KAN-122: auth server actions must not allow account takeover or plan escalation.
 */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  verifyIdToken: vi.fn(),
  getUser: vi.fn(),
  userFindUnique: vi.fn(),
  userCreate: vi.fn(),
}));

vi.mock('next/headers', () => ({
  headers: async () => new Headers({ 'user-agent': 'vitest' }),
  cookies: async () => ({ set: vi.fn(), get: vi.fn(), delete: vi.fn() }),
}));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({
    verifyIdToken: mocks.verifyIdToken,
    getUser: mocks.getUser,
    createSessionCookie: vi.fn().mockResolvedValue('session-cookie'),
  }),
}));
vi.mock('@/lib/firebase/client', () => ({ auth: {} }));
vi.mock('firebase/auth', () => ({ applyActionCode: vi.fn() }));
vi.mock('@/lib/db/client', () => ({
  db: {
    user: { findUnique: mocks.userFindUnique, create: mocks.userCreate, update: vi.fn() },
    userSettings: { create: vi.fn() },
    loginHistory: { findFirst: vi.fn().mockResolvedValue({ id: 'seen-device' }), create: vi.fn() },
  },
}));
vi.mock('@/lib/utils/geo-ip', () => ({ getLocationFromIP: vi.fn().mockResolvedValue(null) }));
vi.mock('@/lib/utils/notifications', () => ({
  notifyNewDeviceLogin: vi.fn(),
  notifyEmailVerified: vi.fn(),
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

import * as authActions from '@/app/actions/auth-actions';

describe('KAN-122: auth server actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.verifyIdToken.mockResolvedValue({ uid: 'uid-1', email: 'new@example.com', email_verified: false });
    mocks.getUser.mockResolvedValue({ uid: 'uid-1', displayName: null, photoURL: null, phoneNumber: null });
    mocks.userFindUnique.mockResolvedValue(null);
    mocks.userCreate.mockResolvedValue({ id: 'user-1', email: 'new@example.com', subscriptionTier: 'free' });
  });

  it('no longer exports the unauthenticated password-reset action that leaked the reset link', () => {
    expect(authActions).not.toHaveProperty('requestPasswordResetAction');
  });

  it('no longer exports the unauthenticated user-sync action', () => {
    expect(authActions).not.toHaveProperty('syncUserAction');
  });

  it.each(['signup', 'login', 'logout'])(
    'no longer ships the unused, unauthenticated /api/auth/%s route',
    (route) => {
      const routeFile = path.resolve(__dirname, '../../../app/api/auth', route, 'route.ts');
      expect(existsSync(routeFile)).toBe(false);
    }
  );

  it.each(['enterprise', 'pro', 'free'])(
    'creates a new user on the free tier even when the client asks for "%s"',
    async (requestedPlan) => {
      // An attacker can still POST extra arguments to the server action; they must be ignored.
      const verifyTokenAction = authActions.verifyTokenAction as unknown as (
        idToken: string,
        metadata?: { selectedPlan?: string }
      ) => Promise<unknown>;

      await verifyTokenAction('id-token', { selectedPlan: requestedPlan });

      expect(mocks.userCreate).toHaveBeenCalledTimes(1);
      expect(mocks.userCreate.mock.calls[0][0].data.subscriptionTier).toBe('free');
    }
  );
});
