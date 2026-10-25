'use server';

import { z } from 'zod';
import { logger } from '@/lib/logger';
import type { ApiResult } from '@/lib/api/server';
import {
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_USER_NOT_FOUND_MESSAGE,
  ADMIN_USERS_PAGE_SIZE,
  adminErrorMessage,
  banAdminUser,
  fetchAdminUser,
  fetchAdminUsers,
  grantAdminRole,
  patchAdminUser,
  removeAdminUser,
  revokeAdminRole,
  toAdminUserDetail,
  toAdminUserSummary,
  unbanAdminUser,
} from '@/lib/api/admin-users';

/**
 * Admin user actions, served by the admin users API (KAN-47) since KAN-184. The API authenticates the session,
 * checks the admin permission on each call and writes the audit log, so these actions only validate input,
 * call the wrapper and turn failures into curated messages.
 *
 * Switched off, with no API behind them: user statistics and notifications to a user (KAN-114), and editing
 * email or subscription fields (the API updates profile fields only; billing lives under KAN-43/KAN-45).
 */

type AdminUserActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/** User ids go into a URL path: only the characters real ids contain are accepted. */
const userIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/, 'Invalid user id');

const MAX_PAGE_SIZE = 100;

function failure(
  result: Extract<ApiResult<unknown>, { success: false }>,
  logMessage: string
): AdminUserActionResponse {
  if (result.status !== 401 && result.status !== 403 && result.status !== 404) {
    logger.error(logMessage, { status: result.status });
  }
  return { success: false, error: adminErrorMessage(result) };
}

function invalidUserId(): AdminUserActionResponse {
  return { success: false, error: ADMIN_USER_NOT_FOUND_MESSAGE };
}

const userFiltersSchema = z.object({
  search: z.string().max(100).optional(),
});

/**
 * Get users with search and pagination
 */
export async function getAllUsersAction(
  page = 1,
  limit = 20,
  filters?: z.infer<typeof userFiltersSchema>
): Promise<AdminUserActionResponse> {
  const parsed = userFiltersSchema.safeParse(filters ?? {});
  const pageSize = Math.min(Math.max(Math.trunc(limit) || ADMIN_USERS_PAGE_SIZE, 1), MAX_PAGE_SIZE);
  const currentPage = Math.max(Math.trunc(page) || 1, 1);
  if (!parsed.success) {
    return { success: false, error: ADMIN_REQUEST_FAILED_MESSAGE };
  }

  const result = await fetchAdminUsers({
    search: parsed.data.search,
    limit: pageSize,
    offset: (currentPage - 1) * pageSize,
  });
  if (!result.success) {
    return failure(result, 'Admin list users failed');
  }

  return {
    success: true,
    data: {
      users: result.data.users.map(toAdminUserSummary),
      pagination: {
        page: currentPage,
        limit: result.data.limit,
        totalCount: result.data.total_count,
        totalPages: Math.ceil(result.data.total_count / result.data.limit),
      },
    },
  };
}

/**
 * Get user by ID
 */
export async function getUserByIdAction(userId: string): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const result = await fetchAdminUser(userId);
  if (!result.success) {
    return failure(result, 'Admin get user failed');
  }
  return { success: true, data: { user: toAdminUserDetail(result.data) } };
}

const updateUserSchema = z.object({
  displayName: z
    .string()
    .max(100, 'Display name must be 100 characters or fewer')
    .nullable()
    .optional(),
  bio: z.string().max(500, 'Bio must be 500 characters or fewer').nullable().optional(),
  location: z.string().max(100, 'Location must be 100 characters or fewer').nullable().optional(),
  website: z.string().max(255, 'Website must be 255 characters or fewer').nullable().optional(),
  phoneNumber: z
    .string()
    .max(32, 'Phone number must be 32 characters or fewer')
    .nullable()
    .optional(),
  avatarUrl: z
    .string()
    .max(2048, 'Avatar URL must be 2048 characters or fewer')
    .nullable()
    .optional(),
});

/**
 * Update a user's profile fields
 */
export async function updateUserAction(
  userId: string,
  data: z.infer<typeof updateUserSchema>
): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const validation = updateUserSchema.safeParse(data);
  if (!validation.success) {
    return { success: false, error: validation.error.issues[0].message };
  }

  const fields = validation.data;
  const result = await patchAdminUser(userId, {
    ...(fields.displayName !== undefined && { display_name: fields.displayName }),
    ...(fields.bio !== undefined && { bio: fields.bio }),
    ...(fields.location !== undefined && { location: fields.location }),
    ...(fields.website !== undefined && { website: fields.website }),
    ...(fields.phoneNumber !== undefined && { phone_number: fields.phoneNumber }),
    ...(fields.avatarUrl !== undefined && { avatar_url: fields.avatarUrl }),
  });
  if (!result.success) {
    return failure(result, 'Admin update user failed');
  }
  return { success: true, data: { user: toAdminUserDetail(result.data) } };
}

/**
 * Delete user
 */
export async function deleteUserAction(userId: string): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const result = await removeAdminUser(userId);
  if (!result.success) {
    return failure(result, 'Admin delete user failed');
  }
  return { success: true, data: { message: 'User deleted successfully' } };
}

const grantAdminRoleSchema = z.object({
  role: z.enum(['admin', 'super_admin']),
  permissions: z.array(z.string().max(100)).max(100),
});

/**
 * Grant admin role to user
 */
export async function grantAdminRoleAction(
  userId: string,
  data: z.infer<typeof grantAdminRoleSchema>
): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const validation = grantAdminRoleSchema.safeParse(data);
  if (!validation.success) {
    return { success: false, error: validation.error.issues[0].message };
  }

  const result = await grantAdminRole(userId, validation.data);
  if (!result.success) {
    return failure(result, 'Admin grant role failed');
  }
  return {
    success: true,
    data: {
      adminUser: { role: result.data.role, permissions: result.data.permissions },
    },
  };
}

/**
 * Revoke admin role
 */
export async function revokeAdminRoleAction(userId: string): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const result = await revokeAdminRole(userId);
  if (!result.success) {
    return failure(result, 'Admin revoke role failed');
  }
  return { success: true, data: { message: 'Admin role revoked successfully' } };
}

/**
 * Ban user (the backend disables the Firebase account)
 */
export async function banUserAction(
  userId: string,
  reason?: string
): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const result = await banAdminUser(userId, reason?.slice(0, 500));
  if (!result.success) {
    return failure(result, 'Admin ban user failed');
  }
  return { success: true, data: { message: 'User banned successfully' } };
}

/**
 * Unban user (the backend enables the Firebase account)
 */
export async function unbanUserAction(userId: string): Promise<AdminUserActionResponse> {
  if (!userIdSchema.safeParse(userId).success) {
    return invalidUserId();
  }
  const result = await unbanAdminUser(userId);
  if (!result.success) {
    return failure(result, 'Admin unban user failed');
  }
  return { success: true, data: { message: 'User unbanned successfully' } };
}
