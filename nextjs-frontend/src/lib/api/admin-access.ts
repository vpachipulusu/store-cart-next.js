import 'server-only';

import { fetchProfile } from './account';
import { fetchAdminUser } from './admin-users';
import type { ApiResult } from './server';

/**
 * Who the admin layout lets in, answered by the API instead of a database read (KAN-50). The caller's own
 * profile gives the user id and the header data; the admin users API then says whether that user is an admin.
 *
 * Deny by default: only an explicit `is_admin` answer with a role grants access. A 401, 403 or 404 from the
 * admin API means "not an admin" (the backend requires the `users.read` permission for that call). Any other
 * failure is returned as a failure, never as access.
 */

export interface AdminAccess {
  user: { email: string; displayName: string | null; avatarUrl: string | null };
  adminRole: string;
}

const NOT_ADMIN_STATUSES: ReadonlySet<number | undefined> = new Set([401, 403, 404]);

/** `data: null` means the caller is not an admin. */
export async function fetchAdminAccess(): Promise<ApiResult<AdminAccess | null>> {
  const profile = await fetchProfile();
  if (!profile.success) return profile;

  const admin = await fetchAdminUser(profile.data.id);
  if (!admin.success) {
    return NOT_ADMIN_STATUSES.has(admin.status) ? { success: true, data: null } : admin;
  }
  if (!admin.data.is_admin || !admin.data.admin_role) return { success: true, data: null };

  return {
    success: true,
    data: {
      user: {
        email: profile.data.email,
        displayName: profile.data.display_name,
        avatarUrl: profile.data.avatar_url,
      },
      adminRole: admin.data.admin_role,
    },
  };
}
