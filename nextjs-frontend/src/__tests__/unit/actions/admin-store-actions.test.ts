// @vitest-environment node
/**
 * KAN-63: the admin store actions re-check admin access, validate the store id before any call, answer
 * failures with curated messages (never backend text) and revalidate the stores page after a change.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'SECRET-sk_live_abc123 postgres://user:pw@host/db';

const mocks = vi.hoisted(() => ({
  suspendAdminStore: vi.fn(),
  unsuspendAdminStore: vi.fn(),
  migrateAdminStore: vi.fn(),
  resolveAdminAccess: vi.fn(),
  revalidatePath: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/api/admin-stores', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/admin-stores')>('@/lib/api/admin-stores');
  return {
    ...actual,
    suspendAdminStore: mocks.suspendAdminStore,
    unsuspendAdminStore: mocks.unsuspendAdminStore,
    migrateAdminStore: mocks.migrateAdminStore,
  };
});
vi.mock('@/lib/api/admin-access', () => ({ resolveAdminAccess: mocks.resolveAdminAccess }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import {
  migrateStoreAction,
  suspendStoreAction,
  unsuspendStoreAction,
} from '@/app/actions/admin-store-actions';
import {
  ADMIN_FORBIDDEN_MESSAGE,
  ADMIN_MIGRATION_FAILED_MESSAGE,
  ADMIN_REQUEST_FAILED_MESSAGE,
  ADMIN_STORE_CONFLICT_MESSAGE,
  ADMIN_STORE_NOT_FOUND_MESSAGE,
} from '@/lib/api/admin-stores';

const ok = <T>(data: T) => ({ success: true as const, data });
const fail = (status?: number) => ({ success: false as const, error: SECRET, status });

const ACTIONS = [
  ['suspendStoreAction', suspendStoreAction, mocks.suspendAdminStore],
  ['unsuspendStoreAction', unsuspendStoreAction, mocks.unsuspendAdminStore],
  ['migrateStoreAction', migrateStoreAction, mocks.migrateAdminStore],
] as const;

describe('admin store actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.resolveAdminAccess.mockResolvedValue({ status: 'admin', viewer: {} });
  });

  describe.each(ACTIONS)('%s', (_name, action, wrapper) => {
    it('rejects a malformed store id before any admin or API call', async () => {
      for (const id of ['', '../users', 'a/b', 'x'.repeat(200), 'id with space']) {
        const result = await action(id);
        expect(result).toEqual({ success: false, error: ADMIN_STORE_NOT_FOUND_MESSAGE });
      }
      expect(mocks.resolveAdminAccess).not.toHaveBeenCalled();
      expect(wrapper).not.toHaveBeenCalled();
    });

    it('refuses a caller who is not an admin without calling the API', async () => {
      mocks.resolveAdminAccess.mockResolvedValue({ status: 'not-admin' });

      const result = await action('store-1');

      expect(result).toEqual({ success: false, error: ADMIN_FORBIDDEN_MESSAGE });
      expect(wrapper).not.toHaveBeenCalled();
    });

    it('refuses a rejected session', async () => {
      mocks.resolveAdminAccess.mockResolvedValue({ status: 'session-rejected' });

      const result = await action('store-1');

      expect(result.success).toBe(false);
      expect(wrapper).not.toHaveBeenCalled();
    });

    it('fails closed and logs when the admin check itself errors', async () => {
      mocks.resolveAdminAccess.mockResolvedValue({ status: 'error', message: SECRET });

      const result = await action('store-1');

      expect(result).toEqual({ success: false, error: ADMIN_REQUEST_FAILED_MESSAGE });
      expect(JSON.stringify(mocks.logError.mock.calls)).not.toContain('SECRET');
      expect(wrapper).not.toHaveBeenCalled();
    });

    it.each([
      [401, ADMIN_FORBIDDEN_MESSAGE, false],
      [403, ADMIN_FORBIDDEN_MESSAGE, false],
      [404, ADMIN_STORE_NOT_FOUND_MESSAGE, false],
      [409, ADMIN_STORE_CONFLICT_MESSAGE, true],
    ])('maps a %s answer to a curated message', async (status, message, logged) => {
      wrapper.mockResolvedValue(fail(status));

      const result = await action('store-1');

      expect(result).toEqual({ success: false, error: message });
      expect(mocks.logError).toHaveBeenCalledTimes(logged ? 1 : 0);
      expect(mocks.revalidatePath).not.toHaveBeenCalled();
    });

    it('never returns backend text', async () => {
      for (const status of [500, 502, 503, undefined]) {
        wrapper.mockResolvedValue(fail(status));
        const result = await action('store-1');
        expect(JSON.stringify(result)).not.toContain('SECRET');
      }
    });
  });

  it('suspendStoreAction suspends, revalidates and reports the change', async () => {
    mocks.suspendAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', status: 'SUSPENDED', changed: true })
    );

    const result = await suspendStoreAction('store-1');

    expect(mocks.suspendAdminStore).toHaveBeenCalledWith('store-1');
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/admin/stores');
    expect(result).toEqual({
      success: true,
      data: { status: 'SUSPENDED', changed: true, message: 'Store suspended' },
    });
  });

  it('suspendStoreAction says so when the store was already suspended', async () => {
    mocks.suspendAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', status: 'SUSPENDED', changed: false })
    );

    const result = await suspendStoreAction('store-1');

    expect(result.data).toMatchObject({ changed: false, message: 'Store was already suspended' });
  });

  it('unsuspendStoreAction unsuspends and revalidates', async () => {
    mocks.unsuspendAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', status: 'ACTIVE', changed: true })
    );

    const result = await unsuspendStoreAction('store-1');

    expect(mocks.unsuspendAdminStore).toHaveBeenCalledWith('store-1');
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/admin/stores');
    expect(result.data).toMatchObject({ status: 'ACTIVE', message: 'Store unsuspended' });
  });

  it('unsuspendStoreAction says so when the store was already active', async () => {
    mocks.unsuspendAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', status: 'ACTIVE', changed: false })
    );

    const result = await unsuspendStoreAction('store-1');

    expect(result.data).toMatchObject({ changed: false, message: 'Store was already active' });
  });

  it('migrateStoreAction reports the versions it moved between', async () => {
    mocks.migrateAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', previous_schema_version: 2, schema_version: 4 })
    );

    const result = await migrateStoreAction('store-1');

    expect(mocks.revalidatePath).toHaveBeenCalledWith('/admin/stores');
    expect(result).toEqual({
      success: true,
      data: {
        previousSchemaVersion: 2,
        schemaVersion: 4,
        message: 'Schema migrated from version 2 to 4',
      },
    });
  });

  it('migrateStoreAction says so when the schema is already current', async () => {
    mocks.migrateAdminStore.mockResolvedValue(
      ok({ store_id: 'store-1', previous_schema_version: 4, schema_version: 4 })
    );

    const result = await migrateStoreAction('store-1');

    expect(result.data).toMatchObject({ message: 'Schema already at version 4' });
  });

  it.each([502, 503])(
    'migrateStoreAction words a %s as a safe-to-retry failure',
    async (status) => {
      mocks.migrateAdminStore.mockResolvedValue(fail(status));

      const result = await migrateStoreAction('store-1');

      expect(result).toEqual({ success: false, error: ADMIN_MIGRATION_FAILED_MESSAGE });
      expect(mocks.logError).toHaveBeenCalledWith('Admin migrate store failed', { status });
    }
  );
});
