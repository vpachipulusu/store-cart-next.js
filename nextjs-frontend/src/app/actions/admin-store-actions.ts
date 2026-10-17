'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { logger } from '@/lib/logger';
import { resolveAdminAccess } from '@/lib/api/admin-access';
import type { ApiResult } from '@/lib/api/server';
import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_STORE_NOT_FOUND_MESSAGE,
  adminErrorMessage,
  migrateAdminStore,
  reprovisionAdminStore,
  reprovisionErrorMessage,
  suspendAdminStore,
  unsuspendAdminStore,
} from '@/lib/api/admin-stores';

/**
 * Admin store actions (KAN-63): suspend, unsuspend, re-run migrations and re-run provisioning through
 * the admin stores API (KAN-201). Each action re-checks admin access on the server, validates the store id, calls the wrapper and
 * turns failures into curated messages; backend text is never returned. The API still authorises every call
 * with the stores.* permissions and writes the audit log.
 */

type ActionResponse<T = unknown> = { success: boolean; data?: T; error?: string };

/** Store ids go into a URL path: only the characters real ids contain are accepted. */
const storeIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/, 'Invalid store id');

const STORES_PATH = '/admin/stores';

function failure(
  result: Extract<ApiResult<unknown>, { success: false }>,
  logMessage: string,
  options: { migration?: boolean; reprovision?: boolean } = {}
): ActionResponse {
  // 401/403/404/409 are expected outcomes (no access, gone, or a state conflict such as a spent re-run cap).
  const expected = [401, 403, 404, 409];
  if (result.status === undefined || !expected.includes(result.status)) {
    logger.error(logMessage, { status: result.status });
  }
  return {
    success: false,
    error: options.reprovision
      ? reprovisionErrorMessage(result)
      : adminErrorMessage(result, options),
  };
}

/** Null when the caller is a confirmed admin, otherwise the response to return. */
async function denyUnlessAdmin(): Promise<ActionResponse | null> {
  const access = await resolveAdminAccess();
  if (access.status === 'admin') return null;
  if (access.status === 'error') {
    logger.error('Admin store action: admin check failed');
    return { success: false, error: ADMIN_REQUEST_FAILED_MESSAGE };
  }
  return { success: false, error: ADMIN_FORBIDDEN_MESSAGE };
}

async function prepare(storeId: string): Promise<ActionResponse | null> {
  if (!storeIdSchema.safeParse(storeId).success) {
    return { success: false, error: ADMIN_STORE_NOT_FOUND_MESSAGE };
  }
  return denyUnlessAdmin();
}

export async function suspendStoreAction(storeId: string): Promise<ActionResponse> {
  const rejected = await prepare(storeId);
  if (rejected) return rejected;

  const result = await suspendAdminStore(storeId);
  if (!result.success) return failure(result, 'Admin suspend store failed');

  revalidatePath(STORES_PATH);
  return {
    success: true,
    data: {
      status: result.data.status,
      changed: result.data.changed,
      message: result.data.changed ? 'Store suspended' : 'Store was already suspended',
    },
  };
}

export async function unsuspendStoreAction(storeId: string): Promise<ActionResponse> {
  const rejected = await prepare(storeId);
  if (rejected) return rejected;

  const result = await unsuspendAdminStore(storeId);
  if (!result.success) return failure(result, 'Admin unsuspend store failed');

  revalidatePath(STORES_PATH);
  return {
    success: true,
    data: {
      status: result.data.status,
      changed: result.data.changed,
      message: result.data.changed ? 'Store unsuspended' : 'Store was already active',
    },
  };
}

export async function migrateStoreAction(storeId: string): Promise<ActionResponse> {
  const rejected = await prepare(storeId);
  if (rejected) return rejected;

  const result = await migrateAdminStore(storeId);
  if (!result.success) return failure(result, 'Admin migrate store failed', { migration: true });

  revalidatePath(STORES_PATH);
  const { previous_schema_version: previous, schema_version: current } = result.data;
  return {
    success: true,
    data: {
      previousSchemaVersion: previous,
      schemaVersion: current,
      message:
        previous === current
          ? `Schema already at version ${current}`
          : `Schema migrated from version ${previous} to ${current}`,
    },
  };
}

export async function reprovisionStoreAction(storeId: string): Promise<ActionResponse> {
  const rejected = await prepare(storeId);
  if (rejected) return rejected;

  const result = await reprovisionAdminStore(storeId);
  if (!result.success) {
    // A 409 means the row on screen is stale (re-run elsewhere, or no longer failed): refresh it too.
    if (result.status === 409) revalidatePath(STORES_PATH);
    return failure(result, 'Admin reprovision store failed', { reprovision: true });
  }

  revalidatePath(STORES_PATH);
  const { status, attempt, max_attempts: maxAttempts } = result.data;
  return {
    success: true,
    data: {
      status,
      attempt,
      maxAttempts,
      message: `Provisioning re-run started (attempt ${attempt} of ${maxAttempts})`,
    },
  };
}
