import 'server-only';

import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
  adminErrorMessage as baseAdminErrorMessage,
} from './admin-errors';
import { callBackend, type ApiResult } from './server';
import {
  banUser,
  deleteUser,
  grantAdmin,
  listUsers,
  readUser,
  revokeAdmin,
  unbanUser,
  updateUser,
  type AdminUserDetail,
  type AdminUserSummary,
  type GrantAdminRequest,
  type UpdateUserRequest,
} from './generated';

/**
 * Server-only calls to the admin users API (KAN-47, `/v1/admin/users`) for the admin pages and server actions
 * (KAN-184). Callers import these instead of the generated SDK (ADR-008). The backend authenticates the session,
 * checks the admin permission on every call and writes the audit log, so nothing here decides who may do what.
 */

export const ADMIN_USERS_PAGE_SIZE = 50;

export { ADMIN_FORBIDDEN_MESSAGE, ADMIN_REQUEST_FAILED_MESSAGE, ADMIN_UNAVAILABLE_MESSAGE };
export const ADMIN_USER_NOT_FOUND_MESSAGE = 'User not found';

/** Search text is capped before it reaches the API; the backend validates again. */
const MAX_SEARCH_LENGTH = 100;

export function fetchAdminUsers(params: { search?: string; limit?: number; offset?: number }) {
  const search = params.search?.trim().slice(0, MAX_SEARCH_LENGTH);
  return callBackend((client) =>
    listUsers({
      client,
      query: {
        limit: params.limit ?? ADMIN_USERS_PAGE_SIZE,
        offset: params.offset ?? 0,
        ...(search ? { search } : {}),
      },
    })
  );
}

export function fetchAdminUser(userId: string) {
  return callBackend((client) => readUser({ client, path: { user_id: userId } }));
}

export function patchAdminUser(userId: string, body: UpdateUserRequest) {
  return callBackend((client) => updateUser({ client, path: { user_id: userId }, body }));
}

export function removeAdminUser(userId: string) {
  return callBackend((client) => deleteUser({ client, path: { user_id: userId } }));
}

export function grantAdminRole(userId: string, body: GrantAdminRequest) {
  return callBackend((client) => grantAdmin({ client, path: { user_id: userId }, body }));
}

export function revokeAdminRole(userId: string) {
  return callBackend((client) => revokeAdmin({ client, path: { user_id: userId } }));
}

export function banAdminUser(userId: string, reason?: string) {
  return callBackend((client) =>
    banUser({ client, path: { user_id: userId }, body: reason ? { reason } : null })
  );
}

export function unbanAdminUser(userId: string) {
  return callBackend((client) => unbanUser({ client, path: { user_id: userId } }));
}

/** Curated message for a failed admin users call; a 404 means the user was not found. */
export function adminErrorMessage(result: Extract<ApiResult<unknown>, { success: false }>): string {
  return baseAdminErrorMessage(result, ADMIN_USER_NOT_FOUND_MESSAGE);
}

/** Browser-facing shapes, in the camelCase the admin UI uses. Only the fields the API returns are exposed. */
export function toAdminUserSummary(user: AdminUserSummary) {
  return {
    id: user.id,
    email: user.email,
    emailVerified: user.email_verified,
    displayName: user.display_name,
    avatarUrl: user.avatar_url,
    createdAt: user.created_at,
    lastLoginAt: user.last_login_at,
    isAdmin: user.is_admin,
    adminRole: user.admin_role,
  };
}

export function toAdminUserDetail(user: AdminUserDetail) {
  return {
    ...toAdminUserSummary(user),
    bio: user.bio,
    location: user.location,
    website: user.website,
    phoneNumber: user.phone_number,
    twoFactorEnabled: user.two_factor_enabled,
    adminPermissions: user.admin_permissions,
  };
}

export type AdminUserSummaryView = ReturnType<typeof toAdminUserSummary>;
export type AdminUserDetailView = ReturnType<typeof toAdminUserDetail>;
