'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import { profileUpdateSchema, userSettingsSchema } from '@/lib/utils/validation';
import { logger } from '@/lib/logger';
import type { ApiResult } from '@/lib/api/server';
import { SESSION_COOKIE_NAME } from '@/lib/api/server';
import {
  changeBackendPassword,
  disableBackendTotp,
  fetchLoginHistory,
  fetchProfile,
  fetchSettings,
  patchAvatar,
  patchProfile,
  patchSettings,
  removeBackendAccount,
  toLoginHistoryEntry,
  toProfile,
  toSettings,
} from '@/lib/api/account';

/**
 * Profile, settings, login history and password actions. Profile data lives behind the FastAPI backend
 * (KAN-41): the API authenticates the session cookie, enforces the verified-email claim and derives the
 * user, so no user id ever comes from the browser.
 *
 * Switched off until their replacements land (the controls are hidden, no Prisma access is left behind):
 * - notifications and data export: KAN-114
 * - 2FA setup stays hidden while KAN-125 (sign-in enforcement) is parked; disable and account deletion take a
 *   fresh ID token from the browser's re-authentication dialog (KAN-180)
 */

/**
 * Response type for user actions
 */
type UserActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

const MAX_HISTORY_PAGE = 100;

/**
 * Logs the failure server-side and returns a stable generic message. Raw `error.message` text from
 * Firebase, the backend or other libraries must never reach the client (KAN-170).
 */
function fail(logMessage: string, error: unknown, publicMessage: string): UserActionResponse {
  logger.error(logMessage, error);
  return { success: false, error: publicMessage };
}

/**
 * Like `fail`, for actions that handle passwords. Firebase errors can embed the arguments of the failing
 * call, so only the error name and code are logged, never the message, stack or error object.
 */
function failSensitive(
  logMessage: string,
  error: unknown,
  publicMessage: string
): UserActionResponse {
  const code = (error as { code?: unknown } | null)?.code;
  logger.error(logMessage, {
    errorName: error instanceof Error ? error.name : typeof error,
    errorCode: typeof code === 'string' ? code : undefined,
  });
  return { success: false, error: publicMessage };
}

/**
 * Maps a failed API result to an action response. No session, an invalid or revoked session, or an
 * unverified email (401/403) is "Unauthorized"; a 404 means the platform user is missing; any other
 * failure is logged and answered with the generic message.
 */
function apiFailure(
  result: Extract<ApiResult<unknown>, { success: false }>,
  logMessage: string,
  publicMessage: string
): UserActionResponse {
  if (result.status === 401 || result.status === 403) {
    return { success: false, error: 'Unauthorized' };
  }
  if (result.status === 404) {
    return { success: false, error: 'User not found' };
  }
  if (result.status === 422) {
    // The backend's validation text is not forwarded; the zod schemas give the user-facing messages.
    return fail(logMessage, { status: result.status }, 'Invalid input');
  }
  return fail(logMessage, { status: result.status, error: result.error }, publicMessage);
}

/**
 * Get user profile
 */
export async function getUserProfileAction(): Promise<UserActionResponse> {
  try {
    const [profile, settings] = await Promise.all([fetchProfile(), fetchSettings()]);
    if (!profile.success) {
      return apiFailure(profile, 'Get user profile error:', 'Failed to get user profile');
    }
    if (!settings.success) {
      return apiFailure(settings, 'Get user profile error:', 'Failed to get user profile');
    }

    return {
      success: true,
      data: { user: { ...toProfile(profile.data), settings: toSettings(settings.data) } },
    };
  } catch (error: unknown) {
    return fail('Get user profile error:', error, 'Failed to get user profile');
  }
}

/**
 * Whether two-factor authentication is enabled, from `two_factor_enabled` on the API profile (KAN-179).
 * Only the boolean is returned; the secret never leaves the backend.
 */
export async function getTwoFactorStatusAction(): Promise<
  UserActionResponse<{ enabled: boolean }>
> {
  try {
    const profile = await fetchProfile();
    if (!profile.success) {
      return apiFailure(profile, 'Get two-factor status error:', 'Failed to get two-factor status');
    }
    return { success: true, data: { enabled: profile.data.two_factor_enabled === true } };
  } catch (error: unknown) {
    return fail('Get two-factor status error:', error, 'Failed to get two-factor status');
  }
}

/**
 * Update user profile
 */
export async function updateUserProfileAction(
  data: z.infer<typeof profileUpdateSchema>
): Promise<UserActionResponse> {
  try {
    // Validate input
    const validation = profileUpdateSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    const result = await patchProfile({
      display_name: validation.data.displayName,
      bio: validation.data.bio,
      location: validation.data.location,
      website: validation.data.website || null,
      phone_number: validation.data.phoneNumber,
    });
    if (!result.success) {
      return apiFailure(result, 'Update user profile error:', 'Failed to update profile');
    }

    return {
      success: true,
      data: { user: toProfile(result.data) },
    };
  } catch (error: unknown) {
    return fail('Update user profile error:', error, 'Failed to update profile');
  }
}

/**
 * Update user avatar
 */
export async function updateUserAvatarAction(avatarUrl: string): Promise<UserActionResponse> {
  try {
    // Validate URL
    const urlSchema = z.string().url();
    const validation = urlSchema.safeParse(avatarUrl);
    if (!validation.success) {
      return {
        success: false,
        error: 'Invalid avatar URL',
      };
    }

    const result = await patchAvatar(avatarUrl);
    if (!result.success) {
      if (result.status === 422) {
        return { success: false, error: 'Invalid avatar URL' };
      }
      return apiFailure(result, 'Update avatar error:', 'Failed to update avatar');
    }

    return {
      success: true,
      data: { avatarUrl: result.data.avatar_url },
    };
  } catch (error: unknown) {
    return fail('Update avatar error:', error, 'Failed to update avatar');
  }
}

/**
 * Get user settings
 */
export async function getUserSettingsAction(): Promise<UserActionResponse> {
  try {
    const result = await fetchSettings();
    if (!result.success) {
      return apiFailure(result, 'Get user settings error:', 'Failed to get settings');
    }

    return {
      success: true,
      data: { settings: toSettings(result.data) },
    };
  } catch (error: unknown) {
    return fail('Get user settings error:', error, 'Failed to get settings');
  }
}

/**
 * Update user settings
 */
export async function updateUserSettingsAction(
  data: z.infer<typeof userSettingsSchema>
): Promise<UserActionResponse> {
  try {
    // Validate input
    const validation = userSettingsSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    const result = await patchSettings({
      theme: validation.data.theme,
      email_notifications: validation.data.emailNotifications,
      language: validation.data.language,
      timezone: validation.data.timezone,
    });
    if (!result.success) {
      return apiFailure(result, 'Update user settings error:', 'Failed to update settings');
    }

    return {
      success: true,
      data: { settings: toSettings(result.data) },
    };
  } catch (error: unknown) {
    return fail('Update user settings error:', error, 'Failed to update settings');
  }
}

async function loadLoginHistory(limit: number, offset: number) {
  const pageSize = Math.min(Math.max(Math.trunc(limit) || 1, 1), MAX_HISTORY_PAGE);
  const start = Math.max(Math.trunc(offset) || 0, 0);
  return fetchLoginHistory(pageSize, start);
}

/**
 * Get user login history
 */
export async function getUserLoginHistoryAction(
  limit = 10,
  offset = 0
): Promise<UserActionResponse> {
  try {
    const result = await loadLoginHistory(limit, offset);
    if (!result.success) {
      return apiFailure(result, 'Get login history error:', 'Failed to get login history');
    }

    return {
      success: true,
      data: {
        loginHistory: result.data.login_history.map(toLoginHistoryEntry),
        totalCount: result.data.total_count,
      },
    };
  } catch (error: unknown) {
    return fail('Get login history error:', error, 'Failed to get login history');
  }
}

/**
 * Get login history (alias for getUserLoginHistoryAction)
 */
export async function getLoginHistoryAction(limit = 10, offset = 0): Promise<UserActionResponse> {
  const result = await getUserLoginHistoryAction(limit, offset);
  if (!result.success || !result.data) {
    return result;
  }
  return {
    success: true,
    data: { history: result.data.loginHistory, totalCount: result.data.totalCount },
  };
}

const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 128;

/**
 * Changes the signed-in user's password (KAN-208). `idToken` is a Firebase ID token the browser just minted by
 * re-authenticating with the CURRENT password (the backend checks it is fresh, belongs to the session and came
 * from the password provider); it is forwarded once and never stored or logged, like `newPassword`.
 *
 * Firebase revokes the user's refresh tokens on a password change, including this session's cookie. After
 * success the browser must sign in again with the new password and call `verifyTokenAction`, or the user is
 * signed out on the next request.
 */
export async function changePasswordAction(
  idToken: string,
  newPassword: string
): Promise<UserActionResponse> {
  try {
    if (typeof idToken !== 'string' || idToken.length === 0) {
      return { success: false, error: 'Re-authentication required' };
    }
    if (typeof newPassword !== 'string' || newPassword.length < MIN_PASSWORD_LENGTH) {
      return { success: false, error: 'New password must be at least 8 characters long' };
    }
    if (newPassword.length > MAX_PASSWORD_LENGTH) {
      return { success: false, error: 'New password must be at most 128 characters long' };
    }

    const result = await changeBackendPassword(idToken, newPassword);
    if (!result.success) {
      if (result.status === 401 || result.status === 403) {
        return { success: false, error: 'Re-authentication required' };
      }
      if (result.status === 422) {
        return { success: false, error: 'Password does not meet requirements' };
      }
      if (result.status === 429) {
        return { success: false, error: 'Too many attempts. Try again later.' };
      }
      return fail('Change password error:', { status: result.status }, 'Failed to change password');
    }
    return { success: true, data: { message: 'Password changed successfully' } };
  } catch (error: unknown) {
    return failSensitive('Change password error:', error, 'Failed to change password');
  }
}

const TWO_FACTOR_CODE = /^\d{6}$/;
const OWNER_CONFLICT_FALLBACK = 'Transfer organization ownership before deleting your account';

/**
 * Deletes the signed-in account (KAN-180). `idToken` is a Firebase ID token the browser just minted by
 * re-authenticating; it is forwarded to the API once and never stored or logged. Organisation owners get
 * the API's 409 message ("transfer ownership first") so they know what to do.
 */
export async function deleteAccountAction(idToken: string): Promise<UserActionResponse> {
  try {
    if (typeof idToken !== 'string' || idToken.length === 0) {
      return { success: false, error: 'Re-authentication required' };
    }
    const result = await removeBackendAccount(idToken);
    if (!result.success) {
      if (result.status === 409) {
        return { success: false, error: result.error || OWNER_CONFLICT_FALLBACK };
      }
      if (result.status === 401 || result.status === 403) {
        return { success: false, error: 'Re-authentication required' };
      }
      return apiFailure(result, 'Delete account error:', 'Failed to delete account');
    }
    (await cookies()).delete(SESSION_COOKIE_NAME);
    return { success: true, data: { message: 'Account deleted' } };
  } catch (error: unknown) {
    return fail('Delete account error:', error, 'Failed to delete account');
  }
}

/** Disables two-factor authentication. Needs the fresh `idToken` and the user's current 6-digit code. */
export async function disableTwoFactorAction(
  idToken: string,
  code: string
): Promise<UserActionResponse> {
  try {
    if (typeof idToken !== 'string' || idToken.length === 0) {
      return { success: false, error: 'Re-authentication required' };
    }
    if (typeof code !== 'string' || !TWO_FACTOR_CODE.test(code)) {
      return { success: false, error: 'Enter the 6-digit code from your authenticator app' };
    }
    const result = await disableBackendTotp(idToken, code);
    if (!result.success) {
      if (result.status === 400) {
        return { success: false, error: 'Invalid authenticator code' };
      }
      if (result.status === 401 || result.status === 403) {
        return { success: false, error: 'Re-authentication required' };
      }
      return apiFailure(result, 'Disable two-factor error:', 'Failed to disable two-factor');
    }
    return { success: true, data: { message: 'Two-factor authentication disabled' } };
  } catch (error: unknown) {
    return fail('Disable two-factor error:', error, 'Failed to disable two-factor');
  }
}
