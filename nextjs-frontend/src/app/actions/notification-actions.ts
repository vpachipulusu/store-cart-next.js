'use server';

import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';
import { getVerifiedUserId } from '@/lib/auth/verified-session';

/**
 * Response type for notification actions
 */
type NotificationActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get recent notifications for authenticated user
 */
export async function getNotificationsAction(
  limit: number = 10
): Promise<NotificationActionResponse> {
  try {
    const userId = await getVerifiedUserId();
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
    });

    const unreadCount = await db.notification.count({
      where: {
        userId,
        read: false,
      },
    });

    return {
      success: true,
      data: {
        notifications,
        unreadCount,
      },
    };
  } catch (error: any) {
    logger.error('Get notifications error:', error);
    return {
      success: false,
      error: 'Failed to get notifications',
    };
  }
}

/**
 * Mark a notification as read
 */
export async function markNotificationAsReadAction(
  notificationId: string
): Promise<NotificationActionResponse> {
  try {
    const userId = await getVerifiedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Verify notification belongs to user
    const notification = await db.notification.findFirst({
      where: {
        id: notificationId,
        userId,
      },
    });

    if (!notification) {
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
    logger.error('Mark notification as read error:', error);
    return {
      success: false,
      error: 'Failed to mark notification as read',
    };
  }
}

/**
 * Mark all notifications as read for authenticated user
 */
export async function markAllNotificationsAsReadAction(): Promise<NotificationActionResponse> {
  try {
    const userId = await getVerifiedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const result = await db.notification.updateMany({
      where: {
        userId,
        read: false,
      },
      data: {
        read: true,
      },
    });

    return {
      success: true,
      data: { count: result.count },
    };
  } catch (error: any) {
    logger.error('Mark all notifications as read error:', error);
    return {
      success: false,
      error: 'Failed to mark all notifications as read',
    };
  }
}

/**
 * Delete a notification
 */
export async function deleteNotificationAction(
  notificationId: string
): Promise<NotificationActionResponse> {
  try {
    const userId = await getVerifiedUserId();
    if (!userId) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Verify notification belongs to user
    const notification = await db.notification.findFirst({
      where: {
        id: notificationId,
        userId,
      },
    });

    if (!notification) {
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
      error: 'Failed to delete notification',
    };
  }
}
