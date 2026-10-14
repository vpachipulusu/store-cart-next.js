// @vitest-environment node
/**
 * KAN-170: user server actions must never return raw Firebase/Prisma/library error text to the
 * client, and must not log secret-bearing error objects (TOTP secrets, passwords, tokens).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'SECRET-sk_live_abc123 postgres://user:pw@host/db';

const mocks = vi.hoisted(() => ({
  getVerifiedUserId: vi.fn(),
  userFindUnique: vi.fn(),
  userUpdate: vi.fn(),
  userDelete: vi.fn(),
  userSettingsFindUnique: vi.fn(),
  userSettingsUpsert: vi.fn(),
  notificationFindMany: vi.fn(),
  notificationCount: vi.fn(),
  notificationUpdate: vi.fn(),
  notificationUpdateMany: vi.fn(),
  notificationDelete: vi.fn(),
  notificationFindFirst: vi.fn(),
  loginHistoryFindMany: vi.fn(),
  loginHistoryCount: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
  notifyPasswordChanged: vi.fn(),
  cancelSubscription: vi.fn(),
  verifyTOTPToken: vi.fn(),
  generateTOTPSecret: vi.fn(),
  cookiesFn: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('next/headers', () => ({ cookies: () => mocks.cookiesFn() }));
vi.mock('@/lib/firebase/admin', () => ({
  getAdminAuth: () => ({ updateUser: mocks.updateUser, deleteUser: mocks.deleteUser }),
}));
vi.mock('@/lib/db/client', () => ({
  db: {
    user: {
      findUnique: mocks.userFindUnique,
      update: mocks.userUpdate,
      delete: mocks.userDelete,
    },
    userSettings: {
      findUnique: mocks.userSettingsFindUnique,
      create: vi.fn(),
      upsert: mocks.userSettingsUpsert,
    },
    notification: {
      findMany: mocks.notificationFindMany,
      count: mocks.notificationCount,
      findFirst: mocks.notificationFindFirst,
      update: mocks.notificationUpdate,
      updateMany: mocks.notificationUpdateMany,
      delete: mocks.notificationDelete,
    },
    loginHistory: { findMany: mocks.loginHistoryFindMany, count: mocks.loginHistoryCount },
  },
}));
vi.mock('@/lib/stripe/subscriptions', () => ({ cancelSubscription: mocks.cancelSubscription }));
vi.mock('@/lib/utils/notifications', () => ({
  notifyPasswordChanged: mocks.notifyPasswordChanged,
}));
vi.mock('@/lib/utils/totp', () => ({
  generateTOTPSecret: mocks.generateTOTPSecret,
  verifyTOTPToken: mocks.verifyTOTPToken,
}));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));

import {
  changePasswordAction,
  deleteAccountAction,
  disable2FAAction,
  exportUserDataAction,
  get2FAStatusAction,
  getLoginHistoryAction,
  getUserNotificationsAction,
  getUserProfileAction,
  getUserSettingsAction,
  initiate2FASetupAction,
  updateUserAvatarAction,
  updateUserProfileAction,
  updateUserSettingsAction,
  verify2FASetupAction,
} from '@/app/actions/user-actions';

const USER = {
  id: 'user-1',
  email: 'a@b.co',
  firebaseUid: 'fb-1',
  twoFactorEnabled: true,
  twoFactorSecret: 'JBSWY3DPEHPK3PXP-totp-secret',
  stripeSubscriptionId: null,
};

function expectNoLeak(result: { success: boolean; error?: string }, generic: string) {
  expect(result.success).toBe(false);
  expect(result.error).toBe(generic);
  expect(JSON.stringify(result)).not.toContain('SECRET');
}

/** Everything handed to the logger, serialised, so a secret anywhere in it is caught. */
function loggedPayload(): string {
  return JSON.stringify(
    mocks.logError.mock.calls.map(([message, meta]) => [
      message,
      meta instanceof Error ? { name: meta.name, message: meta.message, stack: meta.stack } : meta,
    ])
  );
}

describe('KAN-170: user actions return generic errors', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('NEXT_PUBLIC_FIREBASE_API_KEY', 'test-api-key');
    mocks.getVerifiedUserId.mockResolvedValue('user-1');
    mocks.userFindUnique.mockResolvedValue(USER);
    mocks.cookiesFn.mockResolvedValue({ delete: vi.fn() });
    mocks.generateTOTPSecret.mockReturnValue({ secret: 'NEWTOTPSECRET', uri: 'otpauth://x' });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  describe('change password', () => {
    it('hides a Firebase admin failure, never logs the passwords, and logs the error name', async () => {
      fetchMock.mockResolvedValue({ ok: true });
      mocks.updateUser.mockRejectedValue(
        Object.assign(new Error(`${SECRET} newpw-Hunter2!`), { code: 'auth/internal-error' })
      );

      const result = await changePasswordAction('oldpw-Hunter1!', 'newpw-Hunter2!');

      expectNoLeak(result, 'Failed to change password');
      expect(mocks.logError).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ errorName: 'Error', errorCode: 'auth/internal-error' })
      );
      expect(loggedPayload()).not.toContain('SECRET');
      expect(loggedPayload()).not.toContain('Hunter');
    });

    it('hides a network failure of the current-password check', async () => {
      fetchMock.mockRejectedValue(new Error(SECRET));

      expectNoLeak(await changePasswordAction('old', 'newpassword'), 'Failed to change password');
      expect(loggedPayload()).not.toContain('SECRET');
    });

    it('still tells the signed-in user their current password is wrong', async () => {
      fetchMock.mockResolvedValue({ ok: false });

      const result = await changePasswordAction('wrong', 'newpassword');

      expect(result).toEqual({ success: false, error: 'Current password is incorrect' });
      expect(mocks.updateUser).not.toHaveBeenCalled();
    });

    it('keeps the real new-password validation message', async () => {
      const result = await changePasswordAction('old', 'short');

      expect(result).toEqual({
        success: false,
        error: 'New password must be at least 8 characters long',
      });
    });
  });

  describe('delete account', () => {
    it('hides a Firebase delete failure and logs the error object', async () => {
      mocks.deleteUser.mockRejectedValue(new Error(SECRET));

      expectNoLeak(await deleteAccountAction(), 'Failed to delete account');
      expect(mocks.logError).toHaveBeenCalledWith(expect.any(String), expect.any(Error));
    });

    it('hides a database delete failure', async () => {
      mocks.deleteUser.mockResolvedValue(undefined);
      mocks.userDelete.mockRejectedValue(new Error(SECRET));

      expectNoLeak(await deleteAccountAction(), 'Failed to delete account');
    });
  });

  describe('2FA', () => {
    it('setup hides a database failure and never logs the TOTP secret', async () => {
      mocks.userFindUnique.mockResolvedValue({ ...USER, twoFactorEnabled: false });
      mocks.userUpdate.mockRejectedValue(
        new Error(`${SECRET} data: { twoFactorSecret: "NEWTOTPSECRET" }`)
      );

      const result = await initiate2FASetupAction();

      expectNoLeak(result, 'Failed to initiate 2FA setup');
      expect(JSON.stringify(result)).not.toContain('NEWTOTPSECRET');
      expect(mocks.logError).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ errorName: 'Error' })
      );
      expect(loggedPayload()).not.toContain('NEWTOTPSECRET');
      expect(loggedPayload()).not.toContain('SECRET');
    });

    it('setup hides a secret-generation failure', async () => {
      mocks.userFindUnique.mockResolvedValue({ ...USER, twoFactorEnabled: false });
      mocks.generateTOTPSecret.mockImplementation(() => {
        throw new Error(SECRET);
      });

      expectNoLeak(await initiate2FASetupAction(), 'Failed to initiate 2FA setup');
    });

    it('verify hides a failure and never logs the stored secret or the code', async () => {
      mocks.verifyTOTPToken.mockImplementation(() => {
        throw new Error(`${SECRET} ${USER.twoFactorSecret} 123456`);
      });

      expectNoLeak(await verify2FASetupAction('123456'), 'Failed to verify 2FA setup');
      expect(loggedPayload()).not.toContain(USER.twoFactorSecret);
      expect(loggedPayload()).not.toContain('SECRET');
    });

    it('disable hides a failure and never logs the stored secret', async () => {
      mocks.verifyTOTPToken.mockReturnValue(true);
      mocks.userUpdate.mockRejectedValue(new Error(`${SECRET} ${USER.twoFactorSecret}`));

      expectNoLeak(await disable2FAAction('123456'), 'Failed to disable 2FA');
      expect(loggedPayload()).not.toContain(USER.twoFactorSecret);
    });

    it('status hides a database failure', async () => {
      mocks.userFindUnique.mockRejectedValue(new Error(SECRET));

      expectNoLeak(await get2FAStatusAction(), 'Failed to get 2FA status');
      expect(mocks.logError).toHaveBeenCalledWith(expect.any(String), expect.any(Error));
    });

    it('keeps the user-facing "Invalid verification code" message', async () => {
      mocks.verifyTOTPToken.mockReturnValue(false);

      expect(await verify2FASetupAction('000000')).toEqual({
        success: false,
        error: 'Invalid verification code',
      });
      expect(await disable2FAAction('000000')).toEqual({
        success: false,
        error: 'Invalid verification code',
      });
    });
  });

  describe('profile, settings, notifications, history and export', () => {
    const cases: Array<[string, () => Promise<{ success: boolean; error?: string }>, string]> = [
      ['getUserProfileAction', () => getUserProfileAction(), 'Failed to get user profile'],
      [
        'updateUserProfileAction',
        () => updateUserProfileAction({ displayName: 'Valid Name' } as never),
        'Failed to update profile',
      ],
      [
        'updateUserAvatarAction',
        () => updateUserAvatarAction('https://example.com/a.png'),
        'Failed to update avatar',
      ],
      ['getUserSettingsAction', () => getUserSettingsAction(), 'Failed to get settings'],
      [
        'updateUserSettingsAction',
        () =>
          updateUserSettingsAction({
            theme: 'dark',
            emailNotifications: true,
            language: 'en',
            timezone: 'UTC',
          } as never),
        'Failed to update settings',
      ],
      [
        'getUserNotificationsAction',
        () => getUserNotificationsAction(),
        'Failed to get notifications',
      ],
      ['getLoginHistoryAction', () => getLoginHistoryAction(), 'Failed to get login history'],
      ['exportUserDataAction', () => exportUserDataAction(), 'Failed to export data'],
    ];

    it.each(cases)('%s hides a raw failure and logs the error object', async (_name, run, msg) => {
      const boom = new Error(SECRET);
      mocks.userFindUnique.mockRejectedValue(boom);
      mocks.userUpdate.mockRejectedValue(boom);
      mocks.userSettingsFindUnique.mockRejectedValue(boom);
      mocks.userSettingsUpsert.mockRejectedValue(boom);
      mocks.notificationFindMany.mockRejectedValue(boom);
      mocks.notificationCount.mockRejectedValue(boom);
      mocks.loginHistoryFindMany.mockRejectedValue(boom);
      mocks.loginHistoryCount.mockRejectedValue(boom);

      expectNoLeak(await run(), msg);
      expect(mocks.logError).toHaveBeenCalledWith(expect.any(String), expect.any(Error));
    });

    it('updateUserProfileAction pins the real zod validation message', async () => {
      const result = await updateUserProfileAction({ bio: 'x'.repeat(501) } as never);

      expect(result).toEqual({
        success: false,
        error: 'String must contain at most 500 character(s)',
      });
      expect(mocks.userUpdate).not.toHaveBeenCalled();
    });

    it('updateUserSettingsAction pins the real zod validation message', async () => {
      const result = await updateUserSettingsAction({
        theme: 'dark',
        emailNotifications: true,
        language: 'x',
        timezone: 'UTC',
      });

      expect(result).toEqual({
        success: false,
        error: 'String must contain at least 2 character(s)',
      });
      expect(mocks.userSettingsUpsert).not.toHaveBeenCalled();
    });
  });
});
