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
  adminReprovisionStore,
  adminSuspendStore,
  adminUnsuspendStore,
  type StoreStatus,
} from './generated';

/**
 * Server-only calls to the admin organisations and stores API (KAN-201, `/v1/admin/organizations` and
 * `/v1/admin/stores`) for the admin pages and server actions (KAN-63). Callers import these instead of the
 * generated SDK (ADR-008). The backend authenticates the session, checks the stores.* permission on every call
 * and writes the audit log, so nothing here decides who may do what.
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
export const ADMIN_REPROVISION_LIMIT_MESSAGE =
  'This store has used all of its provisioning re-runs.';
export const ADMIN_REPROVISION_NOT_FAILED_MESSAGE =
  'This store has changed (no longer failed, or still provisioning normally), so provisioning cannot be re-run.';
export const ADMIN_REPROVISION_START_FAILED_MESSAGE =
  'Provisioning could not be started. The store is still failed; try again.';

/**
 * The backend answers 409 for two cases and tells them apart only by its error text. It is matched here to pick
 * one of the fixed messages above and is never shown.
 */
const REPROVISION_LIMIT_ERROR = 'Provisioning retry limit reached';

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

export function reprovisionAdminStore(storeId: string) {
  return callBackend((client) => adminReprovisionStore({ client, path: { store_id: storeId } }));
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

/** Curated message for a failed re-run: the 409 cause and a failed start get their own wording. */
export function reprovisionErrorMessage(
  result: Extract<ApiResult<unknown>, { success: false }>
): string {
  if (result.status === 409) {
    return result.error === REPROVISION_LIMIT_ERROR
      ? ADMIN_REPROVISION_LIMIT_MESSAGE
      : ADMIN_REPROVISION_NOT_FAILED_MESSAGE;
  }
  if (result.status === 502 || result.status === 503) return ADMIN_REPROVISION_START_FAILED_MESSAGE;
  return baseAdminErrorMessage(result, ADMIN_STORE_NOT_FOUND_MESSAGE);
}
