import 'server-only';

import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_UNAVAILABLE_MESSAGE,
  adminErrorMessage as baseAdminErrorMessage,
} from './admin-errors';
import { callBackend, type ApiResult } from './server';
import {
  adminListOrganizations,
  adminListStores,
  adminMigrateStore,
  adminSuspendStore,
  adminUnsuspendStore,
  type StoreStatus,
} from './generated';

/**
 * Server-only calls to the admin organisations and stores API (KAN-201, `/v1/admin/organizations` and
 * `/v1/admin/stores`) for the admin pages and server actions (KAN-63). Callers import these instead of the
 * generated SDK (ADR-008). The backend authenticates the session, checks the stores.* permission on every call
 * and writes the audit log, so nothing here decides who may do what. Re-running provisioning is KAN-200.
 */

export const ADMIN_STORES_PAGE_SIZE = 20;
export const ADMIN_STORE_STATUSES: readonly StoreStatus[] = [
  'PROVISIONING',
  'ACTIVE',
  'FAILED',
  'SUSPENDED',
  'ARCHIVED',
];

export type { StoreStatus };
export { ADMIN_FORBIDDEN_MESSAGE, ADMIN_REQUEST_FAILED_MESSAGE, ADMIN_UNAVAILABLE_MESSAGE };
export const ADMIN_STORE_NOT_FOUND_MESSAGE = 'Store not found';
export const ADMIN_STORE_CONFLICT_MESSAGE = 'The store is not in a state that allows this.';
export const ADMIN_MIGRATION_FAILED_MESSAGE =
  'The migration did not complete. Re-running it is safe; try again.';

/** Search text is capped before it reaches the API; the backend validates again. */
const MAX_SEARCH_LENGTH = 100;

function cleanSearch(search: string | undefined): string | undefined {
  const trimmed = search?.trim().slice(0, MAX_SEARCH_LENGTH);
  return trimmed || undefined;
}

export function fetchAdminOrganizations(params: {
  search?: string;
  limit?: number;
  offset?: number;
}) {
  const search = cleanSearch(params.search);
  return callBackend((client) =>
    adminListOrganizations({
      client,
      query: {
        limit: params.limit ?? ADMIN_STORES_PAGE_SIZE,
        offset: params.offset ?? 0,
        ...(search ? { search } : {}),
      },
    })
  );
}

export function fetchAdminStores(params: {
  search?: string;
  status?: StoreStatus;
  organizationId?: string;
  limit?: number;
  offset?: number;
}) {
  const search = cleanSearch(params.search);
  return callBackend((client) =>
    adminListStores({
      client,
      query: {
        limit: params.limit ?? ADMIN_STORES_PAGE_SIZE,
        offset: params.offset ?? 0,
        ...(search ? { search } : {}),
        ...(params.status ? { status: params.status } : {}),
        ...(params.organizationId ? { organization_id: params.organizationId } : {}),
      },
    })
  );
}

export function suspendAdminStore(storeId: string) {
  return callBackend((client) => adminSuspendStore({ client, path: { store_id: storeId } }));
}

export function unsuspendAdminStore(storeId: string) {
  return callBackend((client) => adminUnsuspendStore({ client, path: { store_id: storeId } }));
}

export function migrateAdminStore(storeId: string) {
  return callBackend((client) => adminMigrateStore({ client, path: { store_id: storeId } }));
}

/**
 * Curated message for a failed admin stores call. Only the status picks the wording; backend text is never
 * passed on. `migration` words a 502/503 as a re-runnable migration failure.
 */
export function adminErrorMessage(
  result: Extract<ApiResult<unknown>, { success: false }>,
  options: { migration?: boolean } = {}
): string {
  if (result.status === 409) return ADMIN_STORE_CONFLICT_MESSAGE;
  if (options.migration && (result.status === 502 || result.status === 503)) {
    return ADMIN_MIGRATION_FAILED_MESSAGE;
  }
  return baseAdminErrorMessage(result, ADMIN_STORE_NOT_FOUND_MESSAGE);
}
