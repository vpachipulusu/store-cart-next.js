/**
 * Admin Authentication Middleware
 *
 * Validates admin permissions and roles
 */

import { NextRequest } from 'next/server';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

export interface AdminAuthResult {
  success: boolean;
  userId?: string;
  adminRole?: string;
  permissions?: string[];
  error?: string;
  statusCode?: number;
}

/**
 * Verify admin authentication and permissions
 * @param request - Next.js request object
 * @param requiredPermissions - Optional array of required permissions
 */
export async function verifyAdminAuth(
  request: NextRequest,
  requiredPermissions?: string[]
): Promise<AdminAuthResult> {
  try {
    // Extract token from Authorization header
    const authHeader = request.headers.get('authorization');

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return {
        success: false,
        error: 'Missing or invalid authorization header',
        statusCode: 401,
      };
    }

    const token = authHeader.substring(7);

    // Verify Firebase token
    let decodedToken;
    try {
      decodedToken = await adminAuth.verifyIdToken(token);
    } catch (error) {
      logger.error('Token verification failed:', error);
      return {
        success: false,
        error: 'Invalid or expired token',
        statusCode: 401,
      };
    }

    const firebaseUid = decodedToken.uid;

    // Get user from database
    const user = await db.user.findUnique({
      where: { firebaseUid },
      include: { adminUser: true },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
        statusCode: 404,
      };
    }

    // Check if user is an admin
    if (!user.adminUser) {
      return {
        success: false,
        error: 'Unauthorized: Admin access required',
        statusCode: 403,
      };
    }

    // Extract permissions from JSON
    const permissions = (
      Array.isArray(user.adminUser.permissions) ? user.adminUser.permissions : []
    ) as string[];

    // Check required permissions if specified
    if (requiredPermissions && requiredPermissions.length > 0) {
      const hasAllPermissions = requiredPermissions.every((permission) =>
        permissions.includes(permission)
      );

      if (!hasAllPermissions) {
        return {
          success: false,
          error: 'Unauthorized: Insufficient permissions',
          statusCode: 403,
        };
      }
    }

    return {
      success: true,
      userId: user.id,
      adminRole: user.adminUser.role,
      permissions,
    };
  } catch (error) {
    logger.error('Admin auth verification error:', error);
    return {
      success: false,
      error: 'Authentication verification failed',
      statusCode: 500,
    };
  }
}

/**
 * Check if user has specific permission
 */
export function hasPermission(permissions: string[], requiredPermission: string): boolean {
  return permissions.includes(requiredPermission) || permissions.includes('*');
}

/**
 * Check if user has any of the specified permissions
 */
export function hasAnyPermission(permissions: string[], requiredPermissions: string[]): boolean {
  if (permissions.includes('*')) return true;
  return requiredPermissions.some((permission) => permissions.includes(permission));
}

/**
 * Check if user has all of the specified permissions
 */
export function hasAllPermissions(permissions: string[], requiredPermissions: string[]): boolean {
  if (permissions.includes('*')) return true;
  return requiredPermissions.every((permission) => permissions.includes(permission));
}

/**
 * Common admin permission constants
 */
export const ADMIN_PERMISSIONS = {
  // User management
  USERS_READ: 'users:read',
  USERS_WRITE: 'users:write',
  USERS_DELETE: 'users:delete',

  // Admin management
  ADMINS_READ: 'admins:read',
  ADMINS_WRITE: 'admins:write',
  ADMINS_DELETE: 'admins:delete',

  // Subscription management
  SUBSCRIPTIONS_READ: 'subscriptions:read',
  SUBSCRIPTIONS_WRITE: 'subscriptions:write',
  SUBSCRIPTIONS_DELETE: 'subscriptions:delete',

  // Settings
  SETTINGS_READ: 'settings:read',
  SETTINGS_WRITE: 'settings:write',

  // Analytics
  ANALYTICS_READ: 'analytics:read',

  // Audit logs
  AUDIT_LOGS_READ: 'audit_logs:read',

  // Super admin (all permissions)
  ALL: '*',
} as const;

/**
 * Role-based permission sets
 */
export const ROLE_PERMISSIONS = {
  admin: [
    ADMIN_PERMISSIONS.USERS_READ,
    ADMIN_PERMISSIONS.SUBSCRIPTIONS_READ,
    ADMIN_PERMISSIONS.SETTINGS_READ,
    ADMIN_PERMISSIONS.ANALYTICS_READ,
  ],
  super_admin: [ADMIN_PERMISSIONS.ALL],
} as const;
