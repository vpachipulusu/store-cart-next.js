'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { profileUpdateSchema, userSettingsSchema } from '@/lib/utils/validation';
import { cancelSubscription } from '@/lib/stripe/subscriptions';
import { notifyPasswordChanged } from '@/lib/utils/notifications';
import { generateTOTPSecret, verifyTOTPToken } from '@/lib/utils/totp';
import { logger } from '@/lib/logger';

/**
 * Response type for user actions
 */
type UserActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get authenticated user ID from session
 */
async function getAuthenticatedUserId(): Promise<string | null> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      select: { id: true },
    });

    return user?.id || null;
  } catch (error) {
    logger.error('Authentication error:', error);
    return null;
  }
}

/**
 * Get user profile
 */
export async function getUserProfileAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      include: {
        settings: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    return {
      success: true,
      data: {
        user: {
          id: user.id,
          email: user.email,
          emailVerified: user.emailVerified,
          displayName: user.displayName,
          bio: user.bio,
          avatarUrl: user.avatarUrl,
          location: user.location,
          website: user.website,
          phoneNumber: user.phoneNumber,
          subscriptionTier: user.subscriptionTier,
          subscriptionStatus: user.subscriptionStatus,
          createdAt: user.createdAt,
          settings: user.settings,
        },
      },
    };
  } catch (error: any) {
    logger.error('Get user profile error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get user profile',
    };
  }
}

/**
 * Update user profile
 */
export async function updateUserProfileAction(
  data: z.infer<typeof profileUpdateSchema>
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = profileUpdateSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Update user profile
    const updatedUser = await db.user.update({
      where: { id: userId },
      data: {
        displayName: data.displayName,
        bio: data.bio,
        location: data.location,
        website: data.website || null,
        phoneNumber: data.phoneNumber,
      },
    });

    return {
      success: true,
      data: { user: updatedUser },
    };
  } catch (error: any) {
    logger.error('Update user profile error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update profile',
    };
  }
}

/**
 * Update user avatar
 */
export async function updateUserAvatarAction(avatarUrl: string): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate URL
    const urlSchema = z.string().url();
    const validation = urlSchema.safeParse(avatarUrl);
    if (!validation.success) {
      return {
        success: false,
        error: 'Invalid avatar URL',
      };
    }

    // Update avatar
    const updatedUser = await db.user.update({
      where: { id: userId },
      data: { avatarUrl },
    });

    return {
      success: true,
      data: { avatarUrl: updatedUser.avatarUrl },
    };
  } catch (error: any) {
    logger.error('Update avatar error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update avatar',
    };
  }
}

/**
 * Get user settings
 */
export async function getUserSettingsAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    let settings = await db.userSettings.findUnique({
      where: { userId },
    });

    // Create default settings if not exists
    if (!settings) {
      settings = await db.userSettings.create({
        data: { userId },
      });
    }

    return {
      success: true,
      data: { settings },
    };
  } catch (error: any) {
    logger.error('Get user settings error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get settings',
    };
  }
}

/**
 * Update user settings
 */
export async function updateUserSettingsAction(
  data: z.infer<typeof userSettingsSchema>
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = userSettingsSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Update settings
    const settings = await db.userSettings.upsert({
      where: { userId },
      update: {
        theme: data.theme,
        emailNotifications: data.emailNotifications,
        language: data.language,
        timezone: data.timezone,
      },
      create: {
        userId,
        theme: data.theme,
        emailNotifications: data.emailNotifications,
        language: data.language,
        timezone: data.timezone,
      },
    });

    return {
      success: true,
      data: { settings },
    };
  } catch (error: any) {
    logger.error('Update user settings error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update settings',
    };
  }
}

/**
 * Get user notifications
 */
export async function getUserNotificationsAction(
  limit = 10,
  offset = 0
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const notifications = await db.notification.findMany({
      where: { userId },
      orderBy: { createdAt: 'desc' },
      take: limit,
      skip: offset,
    });

    const totalCount = await db.notification.count({
      where: { userId },
    });

    const unreadCount = await db.notification.count({
      where: { userId, read: false },
    });

    return {
      success: true,
      data: {
        notifications,
        totalCount,
        unreadCount,
      },
    };
  } catch (error: any) {
    logger.error('Get notifications error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get notifications',
    };
  }
}

/**
 * Mark notification as read
 */
export async function markNotificationReadAction(
  notificationId: string
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Verify notification belongs to user
    const notification = await db.notification.findUnique({
      where: { id: notificationId },
    });

    if (!notification || notification.userId !== userId) {
      return {
        success: false,
        error: 'Notification not found',
      };
    }

    // Mark as read
    await db.notification.update({
      where: { id: notificationId },
      data: { read: true },
    });

    return {
      success: true,
      data: { message: 'Notification marked as read' },
    };
  } catch (error: any) {
    logger.error('Mark notification read error:', error);
    return {
      success: false,
      error: error.message || 'Failed to mark notification as read',
    };
  }
}

/**
 * Mark all notifications as read
 */
export async function markAllNotificationsReadAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.notification.updateMany({
      where: { userId, read: false },
      data: { read: true },
    });

    return {
      success: true,
      data: { message: 'All notifications marked as read' },
    };
  } catch (error: any) {
    logger.error('Mark all notifications read error:', error);
    return {
      success: false,
      error: error.message || 'Failed to mark all notifications as read',
    };
  }
}

/**
 * Delete notification
 */
export async function deleteNotificationAction(
  notificationId: string
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Verify notification belongs to user
    const notification = await db.notification.findUnique({
      where: { id: notificationId },
    });

    if (!notification || notification.userId !== userId) {
      return {
        success: false,
        error: 'Notification not found',
      };
    }

    // Delete notification
    await db.notification.delete({
      where: { id: notificationId },
    });

    return {
      success: true,
      data: { message: 'Notification deleted' },
    };
  } catch (error: any) {
    logger.error('Delete notification error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete notification',
    };
  }
}

/**
 * Get user login history
 */
export async function getUserLoginHistoryAction(
  limit = 10,
  offset = 0
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const loginHistory = await db.loginHistory.findMany({
      where: { userId },
      orderBy: { loginAt: 'desc' },
      take: limit,
      skip: offset,
    });

    const totalCount = await db.loginHistory.count({
      where: { userId },
    });

    return {
      success: true,
      data: {
        loginHistory,
        totalCount,
      },
    };
  } catch (error: any) {
    logger.error('Get login history error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get login history',
    };
  }
}

/**
 * Change user password
 * Verifies current password before allowing the change
 */
export async function changePasswordAction(
  currentPassword: string,
  newPassword: string
): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate new password (minimum 8 characters)
    if (!newPassword || newPassword.length < 8) {
      return {
        success: false,
        error: 'New password must be at least 8 characters long',
      };
    }

    // Get user
    const user = await db.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Verify current password via Firebase REST API
    const apiKey = process.env.NEXT_PUBLIC_FIREBASE_API_KEY;
    if (!apiKey) {
      return {
        success: false,
        error: 'Server configuration error',
      };
    }

    const verifyResponse = await fetch(
      `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: user.email,
          password: currentPassword,
          returnSecureToken: false,
        }),
      }
    );

    if (!verifyResponse.ok) {
      return {
        success: false,
        error: 'Current password is incorrect',
      };
    }

    // Update password in Firebase Auth
    await adminAuth.updateUser(user.firebaseUid, {
      password: newPassword,
    });

    // Notify user about password change
    await notifyPasswordChanged(userId);

    return {
      success: true,
      data: { message: 'Password changed successfully' },
    };
  } catch (error: any) {
    logger.error('Change password error:', error);
    return {
      success: false,
      error: error.message || 'Failed to change password',
    };
  }
}

/**
 * Export user data
 */
export async function exportUserDataAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Get all user data
    const user = await db.user.findUnique({
      where: { id: userId },
      include: {
        settings: true,
        loginHistory: true,
        notifications: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Prepare export data
    const exportData = {
      profile: {
        email: user.email,
        displayName: user.displayName,
        bio: user.bio,
        location: user.location,
        website: user.website,
        phoneNumber: user.phoneNumber,
        emailVerified: user.emailVerified,
        createdAt: user.createdAt,
        updatedAt: user.updatedAt,
      },
      settings: user.settings,
      loginHistory: user.loginHistory.map((login) => ({
        loginAt: login.loginAt,
        ipAddress: login.ipAddress,
        userAgent: login.userAgent,
        location: login.location,
        successful: login.successful,
      })),
      notifications: user.notifications.map((notification) => ({
        type: notification.type,
        title: notification.title,
        message: notification.message,
        read: notification.read,
        createdAt: notification.createdAt,
      })),
      subscription: {
        tier: user.subscriptionTier,
        status: user.subscriptionStatus,
      },
    };

    return {
      success: true,
      data: exportData,
    };
  } catch (error: any) {
    logger.error('Export data error:', error);
    return {
      success: false,
      error: error.message || 'Failed to export data',
    };
  }
}

/**
 * Get login history (alias for getUserLoginHistoryAction)
 */
export async function getLoginHistoryAction(limit = 10, offset = 0): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const history = await db.loginHistory.findMany({
      where: { userId },
      orderBy: { loginAt: 'desc' },
      take: limit,
      skip: offset,
    });

    const totalCount = await db.loginHistory.count({
      where: { userId },
    });

    return {
      success: true,
      data: {
        history,
        totalCount,
      },
    };
  } catch (error: any) {
    logger.error('Get login history error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get login history',
    };
  }
}

/**
 * Delete user account (alias for deleteUserAccountAction)
 */
export async function deleteAccountAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Get user
    const user = await db.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Cancel Stripe subscription if exists
    if (user.stripeSubscriptionId) {
      try {
        await cancelSubscription(user.id, true);
      } catch (stripeError) {
        logger.error('Failed to cancel Stripe subscription during account deletion:', stripeError);
        // Continue with deletion even if Stripe cancellation fails
      }
    }

    // Delete from Firebase Auth
    await adminAuth.deleteUser(user.firebaseUid);

    // Delete from database (cascade will handle related records)
    await db.user.delete({
      where: { id: userId },
    });

    // Clear session
    const cookieStore = await cookies();
    cookieStore.delete('session');
    cookieStore.delete('email-verified');

    return {
      success: true,
      data: { message: 'Account deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete account error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete account',
    };
  }
}

/**
 * Delete user account (deprecated - use deleteAccountAction)
 */
export async function deleteUserAccountAction(): Promise<UserActionResponse> {
  return deleteAccountAction();
}

/**
 * Initialize 2FA setup - generates a TOTP secret and returns the URI
 */
export async function initiate2FASetupAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) return { success: false, error: 'Unauthorized' };

    const user = await db.user.findUnique({ where: { id: userId } });
    if (!user) return { success: false, error: 'User not found' };
    if (user.twoFactorEnabled) return { success: false, error: '2FA is already enabled' };

    const { secret, uri } = generateTOTPSecret(user.email);

    // Store the secret (will be confirmed in verify step)
    await db.user.update({
      where: { id: userId },
      data: { twoFactorSecret: secret },
    });

    return { success: true, data: { uri, secret } };
  } catch (error: any) {
    logger.error('Initiate 2FA setup error:', error);
    return { success: false, error: error.message || 'Failed to initiate 2FA setup' };
  }
}

/**
 * Verify and enable 2FA
 */
export async function verify2FASetupAction(token: string): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) return { success: false, error: 'Unauthorized' };

    const user = await db.user.findUnique({ where: { id: userId } });
    if (!user || !user.twoFactorSecret) {
      return { success: false, error: '2FA setup not initiated' };
    }

    const isValid = verifyTOTPToken(token, user.twoFactorSecret);
    if (!isValid) return { success: false, error: 'Invalid verification code' };

    await db.user.update({
      where: { id: userId },
      data: { twoFactorEnabled: true },
    });

    return { success: true, data: { message: '2FA enabled successfully' } };
  } catch (error: any) {
    logger.error('Verify 2FA setup error:', error);
    return { success: false, error: error.message || 'Failed to verify 2FA setup' };
  }
}

/**
 * Disable 2FA (requires valid TOTP token to confirm)
 */
export async function disable2FAAction(token: string): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) return { success: false, error: 'Unauthorized' };

    const user = await db.user.findUnique({ where: { id: userId } });
    if (!user || !user.twoFactorEnabled || !user.twoFactorSecret) {
      return { success: false, error: '2FA is not enabled' };
    }

    const isValid = verifyTOTPToken(token, user.twoFactorSecret);
    if (!isValid) return { success: false, error: 'Invalid verification code' };

    await db.user.update({
      where: { id: userId },
      data: { twoFactorEnabled: false, twoFactorSecret: null },
    });

    return { success: true, data: { message: '2FA disabled successfully' } };
  } catch (error: any) {
    logger.error('Disable 2FA error:', error);
    return { success: false, error: error.message || 'Failed to disable 2FA' };
  }
}

/**
 * Get 2FA status for the current user
 */
export async function get2FAStatusAction(): Promise<UserActionResponse> {
  try {
    const userId = await getAuthenticatedUserId();
    if (!userId) return { success: false, error: 'Unauthorized' };

    const user = await db.user.findUnique({
      where: { id: userId },
      select: { twoFactorEnabled: true },
    });

    if (!user) return { success: false, error: 'User not found' };

    return {
      success: true,
      data: { twoFactorEnabled: user.twoFactorEnabled },
    };
  } catch (error: any) {
    logger.error('Get 2FA status error:', error);
    return { success: false, error: error.message || 'Failed to get 2FA status' };
  }
}
