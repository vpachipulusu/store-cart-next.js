// @vitest-environment node
/**
 * KAN-41: profile, settings, login history and password actions run through the API wrapper.
 * Keeps the guarantees of KAN-123 (verified session only), KAN-126 (only safe profile fields reach the
 * browser) and KAN-170 (no raw error text, no secrets in logs).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'SECRET-sk_live_abc123 postgres://user:pw@host/db';

const mocks = vi.hoisted(() => ({
  fetchProfile: vi.fn(),
  fetchSettings: vi.fn(),
  fetchLoginHistory: vi.fn(),
  patchProfile: vi.fn(),
  patchAvatar: vi.fn(),
  patchSettings: vi.fn(),
  changeBackendPassword: vi.fn(),
  cookieGet: vi.fn(),
  logError: vi.fn(),
  logWarn: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: mocks.cookieGet }),
}));
vi.mock('@/lib/api/account', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/account')>('@/lib/api/account');
  return {
    toProfile: actual.toProfile,
    toSettings: actual.toSettings,
    toLoginHistoryEntry: actual.toLoginHistoryEntry,
    fetchProfile: mocks.fetchProfile,
    fetchSettings: mocks.fetchSettings,
    fetchLoginHistory: mocks.fetchLoginHistory,
    patchProfile: mocks.patchProfile,
    patchAvatar: mocks.patchAvatar,
    patchSettings: mocks.patchSettings,
    changeBackendPassword: mocks.changeBackendPassword,
  };
});
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: mocks.logWarn, error: mocks.logError },
}));

import {
  changePasswordAction,
  getLoginHistoryAction,
  getUserLoginHistoryAction,
  getTwoFactorStatusAction,
  getUserProfileAction,
  getUserSettingsAction,
  updateUserAvatarAction,
  updateUserProfileAction,
  updateUserSettingsAction,
} from '@/app/actions/user-actions';

const API_PROFILE = {
  id: 'user-1',
  email: 'a@b.test',
  email_verified: true,
  display_name: 'Ada',
  bio: 'bio',
  avatar_url: null,
  location: 'London',
  website: null,
  phone_number: null,
  created_at: '2026-01-01T00:00:00Z',
  // Extra server-side fields must never be forwarded to the browser even if the API grows them.
  two_factor_secret: 'JBSWY3DPEHPK3PXP',
  firebase_uid: 'fb-uid-secret',
};
const API_SETTINGS = {
  theme: 'dark',
  email_notifications: true,
  language: 'en',
  timezone: 'UTC',
};
const ok = <T>(data: T) => ({ success: true as const, data });
const failure = (status?: number, error = SECRET) => ({ success: false as const, error, status });

function expectNoLeak(result: { success: boolean; error?: string }, generic: string) {
  expect(result.success).toBe(false);
  expect(result.error).toBe(generic);
  expect(JSON.stringify(result)).not.toContain('SECRET');
}

function loggedPayload(): string {
  return JSON.stringify(mocks.logError.mock.calls);
}

describe('profile actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchProfile.mockResolvedValue(ok(API_PROFILE));
    mocks.fetchSettings.mockResolvedValue(ok(API_SETTINGS));
    mocks.patchProfile.mockResolvedValue(ok(API_PROFILE));
  });

  describe('getTwoFactorStatusAction (KAN-183)', () => {
    it.each([true, false])('reports two_factor_enabled=%s and nothing else', async (enabled) => {
      mocks.fetchProfile.mockResolvedValue(ok({ ...API_PROFILE, two_factor_enabled: enabled }));

      const result = await getTwoFactorStatusAction();

      expect(result).toEqual({ success: true, data: { enabled } });
      expect(JSON.stringify(result)).not.toContain('JBSWY3DPEHPK3PXP');
    });

    it('answers Unauthorized when the API rejects the session', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: 'x', status: 401 });

      expect(await getTwoFactorStatusAction()).toEqual({ success: false, error: 'Unauthorized' });
    });

    it('claims no status when the API is down', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: false, error: SECRET });

      const result = await getTwoFactorStatusAction();

      expect(result).toEqual({ success: false, error: 'Failed to get two-factor status' });
    });
  });

  it('getUserProfileAction returns only the safe profile fields plus settings (KAN-126)', async () => {
    const result = await getUserProfileAction();

    expect(result.success).toBe(true);
    expect(Object.keys(result.data.user).sort()).toEqual(
      [
        'avatarUrl',
        'bio',
        'createdAt',
        'displayName',
        'email',
        'emailVerified',
        'id',
        'location',
        'phoneNumber',
        'settings',
        'website',
      ].sort()
    );
    expect(result.data.user.displayName).toBe('Ada');
    expect(result.data.user.settings).toEqual({
      theme: 'dark',
      emailNotifications: true,
      language: 'en',
      timezone: 'UTC',
    });
    expect(JSON.stringify(result)).not.toContain('JBSWY3DPEHPK3PXP');
    expect(JSON.stringify(result)).not.toContain('fb-uid-secret');
  });

  it('updateUserProfileAction maps the form to the API body and returns only safe fields', async () => {
    const result = await updateUserProfileAction({
      displayName: 'Ada',
      bio: 'bio',
      location: 'London',
      website: '',
      phoneNumber: '',
    });

    expect(mocks.patchProfile).toHaveBeenCalledWith({
      display_name: 'Ada',
      bio: 'bio',
      location: 'London',
      website: null,
      phone_number: '',
    });
    expect(result.success).toBe(true);
    expect(JSON.stringify(result)).not.toContain('JBSWY3DPEHPK3PXP');
  });

  it('updateUserProfileAction pins the real zod validation message without calling the API', async () => {
    const result = await updateUserProfileAction({ bio: 'x'.repeat(501) } as never);

    expect(result).toEqual({
      success: false,
      error: 'String must contain at most 500 character(s)',
    });
    expect(mocks.patchProfile).not.toHaveBeenCalled();
  });

  it('updateUserAvatarAction sends the URL and returns the stored one', async () => {
    mocks.patchAvatar.mockResolvedValue(ok({ ...API_PROFILE, avatar_url: 'https://x.test/a.png' }));

    const result = await updateUserAvatarAction('https://x.test/a.png');

    expect(mocks.patchAvatar).toHaveBeenCalledWith('https://x.test/a.png');
    expect(result).toEqual({ success: true, data: { avatarUrl: 'https://x.test/a.png' } });
  });

  it('updateUserAvatarAction rejects a malformed URL without calling the API', async () => {
    expect(await updateUserAvatarAction('not a url')).toEqual({
      success: false,
      error: 'Invalid avatar URL',
    });
    expect(mocks.patchAvatar).not.toHaveBeenCalled();
  });

  it('updateUserAvatarAction maps an API validation rejection (non-HTTPS) to the same message', async () => {
    mocks.patchAvatar.mockResolvedValue(failure(422, 'Invalid request'));

    expect(await updateUserAvatarAction('http://x.test/a.png')).toEqual({
      success: false,
      error: 'Invalid avatar URL',
    });
  });
});

describe('settings actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchSettings.mockResolvedValue(ok(API_SETTINGS));
    mocks.patchSettings.mockResolvedValue(ok(API_SETTINGS));
  });

  it('getUserSettingsAction returns camelCase settings', async () => {
    const result = await getUserSettingsAction();

    expect(result).toEqual({
      success: true,
      data: {
        settings: { theme: 'dark', emailNotifications: true, language: 'en', timezone: 'UTC' },
      },
    });
  });

  it('updateUserSettingsAction maps to the API body', async () => {
    const result = await updateUserSettingsAction({
      theme: 'dark',
      emailNotifications: true,
      language: 'en',
      timezone: 'UTC',
    });

    expect(mocks.patchSettings).toHaveBeenCalledWith({
      theme: 'dark',
      email_notifications: true,
      language: 'en',
      timezone: 'UTC',
    });
    expect(result.success).toBe(true);
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
    expect(mocks.patchSettings).not.toHaveBeenCalled();
  });
});

describe('login history actions', () => {
  const entry = {
    id: 'h1',
    ip_address: '203.0.113.9',
    user_agent: 'UA',
    location: 'London',
    login_at: '2026-01-02T00:00:00Z',
    successful: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchLoginHistory.mockResolvedValue(ok({ login_history: [entry], total_count: 1 }));
  });

  it('getUserLoginHistoryAction maps entries to camelCase', async () => {
    const result = await getUserLoginHistoryAction(5, 10);

    expect(mocks.fetchLoginHistory).toHaveBeenCalledWith(5, 10);
    expect(result).toEqual({
      success: true,
      data: {
        loginHistory: [
          {
            id: 'h1',
            ipAddress: '203.0.113.9',
            userAgent: 'UA',
            location: 'London',
            loginAt: '2026-01-02T00:00:00Z',
            successful: true,
          },
        ],
        totalCount: 1,
      },
    });
  });

  it('getLoginHistoryAction (alias) returns the page under "history"', async () => {
    const result = await getLoginHistoryAction();

    expect(result.data.history).toHaveLength(1);
    expect(result.data.totalCount).toBe(1);
  });

  it.each([
    [0, -5, 1, 0],
    [1000, 3, 100, 3],
    [Number.NaN, Number.NaN, 1, 0],
  ])(
    'clamps limit %s and offset %s to the API range',
    async (limit, offset, wantLimit, wantOffset) => {
      await getUserLoginHistoryAction(limit, offset);

      expect(mocks.fetchLoginHistory).toHaveBeenCalledWith(wantLimit, wantOffset);
    }
  );
});

describe('API failures', () => {
  const cases: Array<[string, () => Promise<{ success: boolean; error?: string }>, string]> = [
    ['getUserProfileAction', () => getUserProfileAction(), 'Failed to get user profile'],
    [
      'updateUserProfileAction',
      () => updateUserProfileAction({ displayName: 'Ada' }),
      'Failed to update profile',
    ],
    [
      'updateUserAvatarAction',
      () => updateUserAvatarAction('https://x.test/a.png'),
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
        }),
      'Failed to update settings',
    ],
    ['getLoginHistoryAction', () => getLoginHistoryAction(), 'Failed to get login history'],
    ['getUserLoginHistoryAction', () => getUserLoginHistoryAction(), 'Failed to get login history'],
  ];

  function failAll(result: unknown) {
    for (const mock of [
      mocks.fetchProfile,
      mocks.fetchSettings,
      mocks.fetchLoginHistory,
      mocks.patchProfile,
      mocks.patchAvatar,
      mocks.patchSettings,
    ]) {
      mock.mockResolvedValue(result);
    }
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(cases)('%s hides a backend 500 and logs the detail (KAN-170)', async (_n, run, msg) => {
    failAll(failure(500));

    expectNoLeak(await run(), msg);
    expect(mocks.logError).toHaveBeenCalled();
  });

  it.each(cases)('%s hides an unreachable backend', async (_n, run, msg) => {
    failAll(failure(undefined, 'Backend unavailable'));

    expectNoLeak(await run(), msg);
  });

  it.each(cases)('%s hides an unexpected exception', async (_n, run, msg) => {
    for (const mock of [
      mocks.fetchProfile,
      mocks.fetchSettings,
      mocks.fetchLoginHistory,
      mocks.patchProfile,
      mocks.patchAvatar,
      mocks.patchSettings,
    ]) {
      mock.mockRejectedValue(new Error(SECRET));
    }

    expectNoLeak(await run(), msg);
  });

  it.each(cases)(
    '%s answers Unauthorized when the API rejects the session (KAN-123)',
    async (_n, run) => {
      for (const status of [401, 403]) {
        failAll(failure(status, 'Email verification required'));

        expect(await run()).toEqual({ success: false, error: 'Unauthorized' });
      }
    }
  );

  it('answers "User not found" when the platform user is missing', async () => {
    failAll(failure(404, 'Not found'));

    expect(await getUserProfileAction()).toEqual({ success: false, error: 'User not found' });
  });
});

describe('changePasswordAction (KAN-208: forwarded to the backend)', () => {
  const ID_TOKEN = 'fresh-id-token';
  const NEW_PASSWORD = 'newpw-Hunter2!';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('forwards the ID token and the new password to the backend', async () => {
    mocks.changeBackendPassword.mockResolvedValue(ok({}));

    const result = await changePasswordAction(ID_TOKEN, NEW_PASSWORD);

    expect(result).toEqual({ success: true, data: { message: 'Password changed successfully' } });
    expect(mocks.changeBackendPassword).toHaveBeenCalledTimes(1);
    expect(mocks.changeBackendPassword).toHaveBeenCalledWith(ID_TOKEN, NEW_PASSWORD);
  });

  it.each([401, 403])(
    'maps a %s from the backend to "Re-authentication required"',
    async (status) => {
      mocks.changeBackendPassword.mockResolvedValue(failure(status));

      expect(await changePasswordAction(ID_TOKEN, NEW_PASSWORD)).toEqual({
        success: false,
        error: 'Re-authentication required',
      });
    }
  );

  it('maps a 422 to "Password does not meet requirements"', async () => {
    mocks.changeBackendPassword.mockResolvedValue(failure(422));

    expect(await changePasswordAction(ID_TOKEN, NEW_PASSWORD)).toEqual({
      success: false,
      error: 'Password does not meet requirements',
    });
  });

  it('maps a 429 to the rate-limit message', async () => {
    mocks.changeBackendPassword.mockResolvedValue(failure(429));

    expect(await changePasswordAction(ID_TOKEN, NEW_PASSWORD)).toEqual({
      success: false,
      error: 'Too many attempts. Try again later.',
    });
  });

  it.each([500, 503, undefined])(
    'hides a %s backend failure behind a generic message and never logs the passwords',
    async (status) => {
      mocks.changeBackendPassword.mockResolvedValue(failure(status));

      const result = await changePasswordAction(ID_TOKEN, NEW_PASSWORD);

      expectNoLeak(result, 'Failed to change password');
      expect(mocks.logError).toHaveBeenCalled();
      expect(loggedPayload()).not.toContain('SECRET');
      expect(loggedPayload()).not.toContain('Hunter');
      expect(loggedPayload()).not.toContain(ID_TOKEN);
    }
  );

  it('hides an unexpected exception, never logs the passwords, and logs the error name', async () => {
    mocks.changeBackendPassword.mockRejectedValue(
      Object.assign(new Error(`${SECRET} ${NEW_PASSWORD}`), { code: 'auth/internal-error' })
    );

    const result = await changePasswordAction(ID_TOKEN, NEW_PASSWORD);

    expectNoLeak(result, 'Failed to change password');
    expect(mocks.logError).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ errorName: 'Error', errorCode: 'auth/internal-error' })
    );
    expect(loggedPayload()).not.toContain('SECRET');
    expect(loggedPayload()).not.toContain('Hunter');
  });

  it.each([
    ['empty', ''],
    ['not a string', undefined],
  ])('requires an ID token (%s) without calling the backend', async (_label, token) => {
    expect(await changePasswordAction(token as never, NEW_PASSWORD)).toEqual({
      success: false,
      error: 'Re-authentication required',
    });
    expect(mocks.changeBackendPassword).not.toHaveBeenCalled();
  });

  it('keeps the real new-password length messages without calling the backend', async () => {
    expect(await changePasswordAction(ID_TOKEN, 'short')).toEqual({
      success: false,
      error: 'New password must be at least 8 characters long',
    });
    expect(await changePasswordAction(ID_TOKEN, 'x'.repeat(129))).toEqual({
      success: false,
      error: 'New password must be at most 128 characters long',
    });
    expect(mocks.changeBackendPassword).not.toHaveBeenCalled();
  });

  it('accepts the boundary lengths 8 and 128', async () => {
    mocks.changeBackendPassword.mockResolvedValue(ok({}));

    expect((await changePasswordAction(ID_TOKEN, 'x'.repeat(8))).success).toBe(true);
    expect((await changePasswordAction(ID_TOKEN, 'x'.repeat(128))).success).toBe(true);
  });
});
