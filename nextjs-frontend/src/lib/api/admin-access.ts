import 'server-only';

import { fetchProfile } from './account';
import { isSessionRejected } from './session-rejected';

/**
 * Server-only admin check for the /admin layout (KAN-50). `GET /v1/me` reports `is_admin` and `admin_role`
 * (KAN-204). They are a UI hint only: every admin API route still authorises the caller on the backend.
 *
 * Fails closed: only an OK response whose `is_admin` is exactly `true` grants access, every other outcome is
 * a denial the layout turns into a redirect or an error page.
 */

export type AdminViewer = {
  email: string;
  displayName: string | null;
  avatarUrl: string | null;
  adminRole: string;
};

export type AdminAccess =
  | { status: 'admin'; viewer: AdminViewer }
  | { status: 'not-admin' }
  | { status: 'session-rejected' }
  | { status: 'error'; message: string };

export async function resolveAdminAccess(): Promise<AdminAccess> {
  const result = await fetchProfile();
  if (!result.success) {
    if (isSessionRejected(result)) return { status: 'session-rejected' };
    return {
      status: 'error',
      message: `Profile request failed (${result.status ?? 'unreachable'})`,
    };
  }

  const profile = result.data;
  // The response is validated, not trusted: anything but a true flag, a non-empty string role and a string
  // email is no access (an admin without a role also cannot be rendered in the header).
  if (
    profile?.is_admin !== true ||
    typeof profile.admin_role !== 'string' ||
    profile.admin_role === '' ||
    typeof profile.email !== 'string'
  ) {
    return { status: 'not-admin' };
  }

  return {
    status: 'admin',
    viewer: {
      email: profile.email,
      displayName: profile.display_name ?? null,
      avatarUrl: profile.avatar_url ?? null,
      adminRole: profile.admin_role,
    },
  };
}
