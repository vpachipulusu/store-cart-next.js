// @vitest-environment node
/** KAN-60: onboarding actions validate input, need a verified session, and never leak backend text. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getVerifiedSessionClaims: vi.fn(),
  createOrganizationWithStore: vi.fn(),
  fetchStoreStatus: vi.fn(),
  revalidatePath: vi.fn(),
}));

vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/logger', () => ({ logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedSessionClaims: mocks.getVerifiedSessionClaims,
  isEmailNotVerifiedError: () => false,
}));
vi.mock('@/lib/api/onboarding', () => ({
  createOrganizationWithStore: mocks.createOrganizationWithStore,
  fetchStoreStatus: mocks.fetchStoreStatus,
}));

import { createStoreAction, getStoreStatusAction } from '@/app/actions/onboarding-actions';

const INPUT = {
  organizationName: 'Acme',
  organizationSlug: 'acme',
  storeName: 'Acme Shop',
  storeSlug: 'acme-shop',
};
const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';

describe('createStoreAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedSessionClaims.mockResolvedValue({ uid: 'u1' });
  });

  it('creates the organisation and store and returns the store id', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: true,
      storeId: STORE_ID,
      organizationId: 'o1',
      resumed: false,
    });
    expect(await createStoreAction(INPUT)).toEqual({ success: true, data: { storeId: STORE_ID } });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard', 'layout');
  });

  it('rejects invalid input with field errors and never calls the backend', async () => {
    const result = await createStoreAction({ ...INPUT, storeSlug: 'Bad Slug' });
    expect(result.success).toBe(false);
    expect(result.fieldErrors?.storeSlug).toBeDefined();
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('rejects a request without a verified session', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);
    expect(await createStoreAction(INPUT)).toEqual({ success: false, error: 'Unauthorized' });
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('treats an unverified or revoked session as unauthorized', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(new Error('revoked'));
    expect(await createStoreAction(INPUT)).toEqual({ success: false, error: 'Unauthorized' });
  });

  it('answers a taken slug on the store field', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: false,
      reason: 'slug_taken',
      stage: 'store',
      organizationId: 'o1',
    });
    const result = await createStoreAction(INPUT);
    expect(result.success).toBe(false);
    expect(result.fieldErrors?.storeSlug).toMatch(/taken/i);
  });

  it('answers a taken organisation slug on the organisation field', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: false,
      reason: 'slug_taken',
      stage: 'organization',
    });
    expect((await createStoreAction(INPUT)).fieldErrors?.organizationSlug).toMatch(/taken/i);
  });

  it('answers a rejected address (422) on the matching slug field', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: false,
      reason: 'invalid',
      stage: 'organization',
    });
    expect((await createStoreAction(INPUT)).fieldErrors?.organizationSlug).toMatch(
      /cannot be used/i
    );
  });

  it('tells the user a half-finished setup is saved and a retry resumes it', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: false,
      reason: 'unavailable',
      stage: 'store',
      organizationId: 'o1',
    });
    const result = await createStoreAction(INPUT);
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/business was created/i);
  });

  it.each(['limit', 'already_onboarded', 'unavailable'] as const)(
    'maps %s to a generic user message',
    async (reason) => {
      mocks.createOrganizationWithStore.mockResolvedValue({
        success: false,
        reason,
        stage: 'organization',
      });
      const result = await createStoreAction(INPUT);
      expect(result.success).toBe(false);
      expect(result.error).toBeTruthy();
    }
  );

  it('does not leak a thrown error message', async () => {
    mocks.createOrganizationWithStore.mockRejectedValue(new Error('secret db url'));
    const result = await createStoreAction(INPUT);
    expect(result.success).toBe(false);
    expect(result.error).not.toMatch(/secret/);
  });
});

describe('getStoreStatusAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedSessionClaims.mockResolvedValue({ uid: 'u1' });
  });

  it('returns the status for a store the backend lets the caller read', async () => {
    mocks.fetchStoreStatus.mockResolvedValue({
      success: true,
      data: { id: STORE_ID, name: 'Acme Shop', status: 'ACTIVE' },
    });
    expect(await getStoreStatusAction(STORE_ID)).toEqual({
      success: true,
      data: { status: 'ACTIVE', name: 'Acme Shop' },
    });
  });

  it('rejects a malformed id without calling the backend', async () => {
    expect((await getStoreStatusAction('bad id!')).success).toBe(false);
    expect(mocks.fetchStoreStatus).not.toHaveBeenCalled();
  });

  it('rejects a request without a verified session', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);
    expect(await getStoreStatusAction(STORE_ID)).toEqual({ success: false, error: 'Unauthorized' });
    expect(mocks.fetchStoreStatus).not.toHaveBeenCalled();
  });

  it('answers not available for a store that is not the caller own', async () => {
    mocks.fetchStoreStatus.mockResolvedValue({ success: false, reason: 'not_found' });
    expect(await getStoreStatusAction(STORE_ID)).toMatchObject({
      success: false,
      notFound: true,
    });
  });

  it('answers a retryable error when the backend is unavailable', async () => {
    mocks.fetchStoreStatus.mockResolvedValue({ success: false, reason: 'unavailable' });
    const result = await getStoreStatusAction(STORE_ID);
    expect(result).toMatchObject({ success: false });
    expect(result.notFound).toBeUndefined();
  });
});
