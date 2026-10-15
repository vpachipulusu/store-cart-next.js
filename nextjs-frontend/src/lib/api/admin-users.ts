import 'server-only';

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

export const ADMIN_FORBIDDEN_MESSAGE = 'You do not have permission to do that';
export const ADMIN_USER_NOT_FOUND_MESSAGE = 'User not found';
export const ADMIN_REQUEST_FAILED_MESSAGE = 'Something went wrong. Please try again.';
export const ADMIN_UNAVAILABLE_MESSAGE =
  'The admin service is unavailable. Please try again later.';

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

/**
 * Curated message for a failed admin API result. Backend error text is never passed through: only the status
 * decides the wording, so raw detail (ids, SQL, upstream errors) cannot reach the admin's browser.
 */
export function adminErrorMessage(result: Extract<ApiResult<unknown>, { success: false }>): string {
  switch (result.status) {
    case 401:
    case 403:
      return ADMIN_FORBIDDEN_MESSAGE;
    case 404:
      return ADMIN_USER_NOT_FOUND_MESSAGE;
    case undefined:
      return ADMIN_UNAVAILABLE_MESSAGE;
    default:
      return ADMIN_REQUEST_FAILED_MESSAGE;
  }
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
