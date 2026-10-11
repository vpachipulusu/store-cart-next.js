'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * Response type for admin user actions
 */
type AdminUserActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get authenticated admin user
 */
async function getAuthenticatedAdmin() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        adminUser: true,
      },
    });

    if (!user || !user.adminUser) {
      return null;
    }

    return user;
  } catch (error) {
    logger.error('Admin authentication error:', error);
    return null;
  }
}

/**
 * Check if user has admin permission
 */
function hasPermission(admin: any, permission: string): boolean {
  const permissions = admin.adminUser?.permissions as string[] || [];
  return permissions.includes(permission) || permissions.includes('*');
}

/**
 * User filters schema
 */
const userFiltersSchema = z.object({
  search: z.string().optional(),
  subscriptionTier: z.string().optional(),
  subscriptionStatus: z.string().optional(),
  emailVerified: z.boolean().optional(),
  isAdmin: z.boolean().optional(),
});

/**
 * Get all users with filters and pagination
 */
export async function getAllUsersAction(
  page = 1,
  limit = 20,
  filters?: z.infer<typeof userFiltersSchema>
): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Build where clause
    const where: any = {};

    if (filters?.search) {
      where.OR = [
        { email: { contains: filters.search, mode: 'insensitive' } },
        { displayName: { contains: filters.search, mode: 'insensitive' } },
      ];
    }

    if (filters?.subscriptionTier) {
      where.subscriptionTier = filters.subscriptionTier;
    }

    if (filters?.subscriptionStatus) {
      where.subscriptionStatus = filters.subscriptionStatus;
    }

    if (filters?.emailVerified !== undefined) {
      where.emailVerified = filters.emailVerified;
    }

    if (filters?.isAdmin !== undefined) {
      where.adminUser = filters.isAdmin ? { isNot: null } : { is: null };
    }

    // Get users with pagination
    const [users, totalCount] = await Promise.all([
      db.user.findMany({
        where,
        include: {
          adminUser: true,
          settings: true,
        },
        orderBy: { createdAt: 'desc' },
        take: limit,
        skip: (page - 1) * limit,
      }),
      db.user.count({ where }),
    ]);

    return {
      success: true,
      data: {
        users: users.map((user) => ({
          id: user.id,
          firebaseUid: user.firebaseUid,
          email: user.email,
          emailVerified: user.emailVerified,
          displayName: user.displayName,
          avatarUrl: user.avatarUrl,
          subscriptionTier: user.subscriptionTier,
          subscriptionStatus: user.subscriptionStatus,
          isAdmin: !!user.adminUser,
          createdAt: user.createdAt,
          lastLoginAt: user.lastLoginAt,
        })),
        pagination: {
          page,
          limit,
          totalCount,
          totalPages: Math.ceil(totalCount / limit),
        },
      },
    };
  } catch (error: any) {
    logger.error('Get all users error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get users',
    };
  }
}

/**
 * Get user by ID
 */
export async function getUserByIdAction(userId: string): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
      include: {
        settings: true,
        adminUser: true,
        loginHistory: {
          orderBy: { loginAt: 'desc' },
          take: 10,
        },
        notifications: {
          orderBy: { createdAt: 'desc' },
          take: 10,
        },
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
      data: { user },
    };
  } catch (error: any) {
    logger.error('Get user by ID error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get user',
    };
  }
}

/**
 * Update user schema
 */
const updateUserSchema = z.object({
  email: z.string().email().optional(),
  displayName: z.string().optional(),
  emailVerified: z.boolean().optional(),
  subscriptionTier: z.string().optional(),
  subscriptionStatus: z.string().optional(),
});

/**
 * Update user
 */
export async function updateUserAction(
  userId: string,
  data: z.infer<typeof updateUserSchema>
): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.update')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = updateUserSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Update user
    const updatedUser = await db.user.update({
      where: { id: userId },
      data: {
        email: data.email,
        displayName: data.displayName,
        emailVerified: data.emailVerified,
        subscriptionTier: data.subscriptionTier,
        subscriptionStatus: data.subscriptionStatus,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'user.updated',
        resource: 'User',
        resourceId: userId,
        metadata: { updatedFields: Object.keys(data) },
      },
    });

    return {
      success: true,
      data: { user: updatedUser },
    };
  } catch (error: any) {
    logger.error('Update user error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update user',
    };
  }
}

/**
 * Delete user
 */
export async function deleteUserAction(userId: string): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.delete')) {
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

    // Delete from Firebase Auth
    try {
      await adminAuth.deleteUser(user.firebaseUid);
    } catch (error) {
      logger.error('Firebase delete error:', error);
    }

    // Delete from database
    await db.user.delete({
      where: { id: userId },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'user.deleted',
        resource: 'User',
        resourceId: userId,
        metadata: { email: user.email },
      },
    });

    return {
      success: true,
      data: { message: 'User deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete user error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete user',
    };
  }
}

/**
 * Grant admin role schema
 */
const grantAdminRoleSchema = z.object({
  role: z.enum(['admin', 'super_admin']),
  permissions: z.array(z.string()),
});

/**
 * Grant admin role to user
 */
export async function grantAdminRoleAction(
  userId: string,
  data: z.infer<typeof grantAdminRoleSchema>
): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'admins.create')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = grantAdminRoleSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Create or update admin user
    const adminUser = await db.adminUser.upsert({
      where: { userId },
      update: {
        role: data.role,
        permissions: data.permissions,
      },
      create: {
        userId,
        role: data.role,
        permissions: data.permissions,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'admin.granted',
        resource: 'AdminUser',
        resourceId: userId,
        metadata: { role: data.role, permissions: data.permissions },
      },
    });

    return {
      success: true,
      data: { adminUser },
    };
  } catch (error: any) {
    logger.error('Grant admin role error:', error);
    return {
      success: false,
      error: error.message || 'Failed to grant admin role',
    };
  }
}

/**
 * Revoke admin role
 */
export async function revokeAdminRoleAction(userId: string): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'admins.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Delete admin user
    await db.adminUser.delete({
      where: { userId },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'admin.revoked',
        resource: 'AdminUser',
        resourceId: userId,
      },
    });

    return {
      success: true,
      data: { message: 'Admin role revoked successfully' },
    };
  } catch (error: any) {
    logger.error('Revoke admin role error:', error);
    return {
      success: false,
      error: error.message || 'Failed to revoke admin role',
    };
  }
}

/**
 * Get user statistics
 */
export async function getUserStatsAction(): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const [
      totalUsers,
      verifiedUsers,
      adminUsers,
      activeSubscriptions,
      newUsersThisMonth,
    ] = await Promise.all([
      db.user.count(),
      db.user.count({ where: { emailVerified: true } }),
      db.adminUser.count(),
      db.user.count({ where: { subscriptionStatus: 'active' } }),
      db.user.count({
        where: {
          createdAt: {
            gte: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
          },
        },
      }),
    ]);

    return {
      success: true,
      data: {
        totalUsers,
        verifiedUsers,
        adminUsers,
        activeSubscriptions,
        newUsersThisMonth,
      },
    };
  } catch (error: any) {
    logger.error('Get user stats error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get user statistics',
    };
  }
}

/**
 * Ban user (disable Firebase account)
 */
export async function banUserAction(userId: string, reason?: string): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.update')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Disable user in Firebase
    await adminAuth.updateUser(user.firebaseUid, {
      disabled: true,
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'user.banned',
        resource: 'User',
        resourceId: userId,
        metadata: { reason },
      },
    });

    return {
      success: true,
      data: { message: 'User banned successfully' },
    };
  } catch (error: any) {
    logger.error('Ban user error:', error);
    return {
      success: false,
      error: error.message || 'Failed to ban user',
    };
  }
}

/**
 * Unban user (enable Firebase account)
 */
export async function unbanUserAction(userId: string): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'users.update')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const user = await db.user.findUnique({
      where: { id: userId },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    // Enable user in Firebase
    await adminAuth.updateUser(user.firebaseUid, {
      disabled: false,
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'user.unbanned',
        resource: 'User',
        resourceId: userId,
      },
    });

    return {
      success: true,
      data: { message: 'User unbanned successfully' },
    };
  } catch (error: any) {
    logger.error('Unban user error:', error);
    return {
      success: false,
      error: error.message || 'Failed to unban user',
    };
  }
}

/**
 * Send notification to user
 */
export async function sendUserNotificationAction(
  userId: string,
  notification: { type: string; title: string; message: string; link?: string }
): Promise<AdminUserActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'notifications.create')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Create notification
    await db.notification.create({
      data: {
        userId,
        type: notification.type,
        title: notification.title,
        message: notification.message,
        link: notification.link,
      },
    });

    return {
      success: true,
      data: { message: 'Notification sent successfully' },
    };
  } catch (error: any) {
    logger.error('Send notification error:', error);
    return {
      success: false,
      error: error.message || 'Failed to send notification',
    };
  }
}
