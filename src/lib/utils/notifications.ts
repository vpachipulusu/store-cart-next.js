import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

export type NotificationType =
  | 'login_new_device'
  | 'password_changed'
  | 'subscription_changed'
  | 'email_verified'
  | 'account_created'
  | 'payment_failed'
  | 'trial_ending';

interface CreateNotificationParams {
  userId: string;
  type: NotificationType;
  title: string;
  message: string;
  link?: string;
}

export async function createNotification(params: CreateNotificationParams) {
  try {
    await db.notification.create({
      data: {
        userId: params.userId,
        type: params.type,
        title: params.title,
        message: params.message,
        link: params.link,
      },
    });
  } catch (error) {
    // Non-critical — notification creation should never break the main flow
    logger.error('Failed to create notification:', error);
  }
}

export async function notifyPasswordChanged(userId: string) {
  await createNotification({
    userId,
    type: 'password_changed',
    title: 'Password Changed',
    message:
      'Your password was changed successfully. If you did not make this change, please contact support immediately.',
    link: '/dashboard/security',
  });
}

export async function notifyNewDeviceLogin(
  userId: string,
  ipAddress: string
) {
  await createNotification({
    userId,
    type: 'login_new_device',
    title: 'New Login Detected',
    message: `A new login was detected from IP ${ipAddress}. If this wasn't you, please change your password.`,
    link: '/dashboard/security',
  });
}

export async function notifySubscriptionChanged(
  userId: string,
  newTier: string
) {
  await createNotification({
    userId,
    type: 'subscription_changed',
    title: 'Subscription Updated',
    message: `Your subscription has been changed to the ${newTier} plan.`,
    link: '/dashboard/settings',
  });
}

export async function notifyEmailVerified(userId: string) {
  await createNotification({
    userId,
    type: 'email_verified',
    title: 'Email Verified',
    message: 'Your email address has been verified successfully.',
  });
}

export async function notifyPaymentFailed(userId: string) {
  await createNotification({
    userId,
    type: 'payment_failed',
    title: 'Payment Failed',
    message:
      'Your latest payment failed. Please update your payment method to avoid service interruption.',
    link: '/dashboard/settings',
  });
}
