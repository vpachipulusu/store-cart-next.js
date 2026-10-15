// @vitest-environment node
/** KAN-60: onboarding actions validate input, need a verified session, and never leak backend text. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getVerifiedSessionClaims: vi.fn(),
  createOrganizationWithStore: vi.fn(),
  fetchStoreStatus: vi.fn(),
  revalidatePath: vi.fn(),
  loggerError: vi.fn(),
}));

vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/logger', () => ({
  logger: { error: mocks.loggerError, warn: vi.fn(), info: vi.fn() },
}));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedSessionClaims: mocks.getVerifiedSessionClaims,
  isEmailNotVerifiedError: () => false,
}));
vi.mock('@/lib/api/onboarding', () => ({
  createOrganizationWithStore: mocks.createOrganizationWithStore,
  fetchStoreStatus: mocks.fetchStoreStatus,
}));

import { createStoreAction, getStoreStatusAction } from '@/app/actions/onboarding-actions';

const NEW = {
  mode: 'new',
  organizationName: 'Acme',
  organizationSlug: 'acme',
  storeName: 'Acme Shop',
  storeSlug: 'acme-shop',
} as const;
const RESUME = { mode: 'resume', storeName: 'Acme Shop', storeSlug: 'acme-shop' } as const;
const STORE_ID = 'tz4a98xxat96iws9zmbrgj3a';

const fail = (reason: string, stage: 'organization' | 'store', organizationId?: string) => ({
  success: false,
  reason,
  stage,
  ...(organizationId ? { organizationId } : {}),
});

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
    expect(await createStoreAction(NEW)).toEqual({ success: true, data: { storeId: STORE_ID } });
    expect(mocks.createOrganizationWithStore).toHaveBeenCalledWith({
      organizationName: 'Acme',
      organizationSlug: 'acme',
      storeName: 'Acme Shop',
      storeSlug: 'acme-shop',
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard', 'layout');
  });

  it('accepts a store-only resume request without any business fields', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue({
      success: true,
      storeId: STORE_ID,
      organizationId: 'o1',
      resumed: true,
    });
    expect((await createStoreAction(RESUME)).success).toBe(true);
    expect(mocks.createOrganizationWithStore).toHaveBeenCalledWith({
      storeName: 'Acme Shop',
      storeSlug: 'acme-shop',
    });
  });

  it('rejects invalid input with field errors and never calls the backend', async () => {
    const result = await createStoreAction({ ...NEW, storeSlug: 'Bad Slug' });
    expect(result.success).toBe(false);
    expect(result.fieldErrors?.storeSlug).toBeDefined();
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('still requires valid business fields in new mode', async () => {
    const result = await createStoreAction({ ...NEW, organizationName: '   ' });
    expect(result.fieldErrors?.organizationName).toBeDefined();
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('answers the unauthorized code, with no text, when there is no verified session', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);
    expect(await createStoreAction(NEW)).toEqual({ success: false, code: 'unauthorized' });
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('treats a revoked session as unauthorized without logging it as an outage', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(
      Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' })
    );
    expect(await createStoreAction(NEW)).toEqual({ success: false, code: 'unauthorized' });
    expect(mocks.loggerError).not.toHaveBeenCalled();
  });

  it('logs an unexpected session-check failure and reports a retryable error, not an expired session', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(new Error('firebase down'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      error: 'We could not set up your store. Please try again.',
    });
    expect(mocks.loggerError).toHaveBeenCalled();
    expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
  });

  it('gives a form-level message when a resume request finds no business to resume', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('invalid', 'organization'));
    expect(await createStoreAction(RESUME)).toEqual({
      success: false,
      error: 'We could not find your business. Reload the page and try again.',
    });
  });

  it.each([null, {}, { mode: 'bogus' }])(
    'rejects a malformed submission %j with a message',
    async (bad) => {
      const result = await createStoreAction(bad as never);
      expect(result.success).toBe(false);
      expect(result.error ?? Object.keys(result.fieldErrors ?? {}).length).toBeTruthy();
      expect(mocks.createOrganizationWithStore).not.toHaveBeenCalled();
    }
  );

  it('maps a backend unauthorized result to the unauthorized code', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('unauthorized', 'organization'));
    expect(await createStoreAction(NEW)).toEqual({ success: false, code: 'unauthorized' });
  });

  it('answers a taken store slug on the store field and flags the created business', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('slug_taken', 'store', 'o1'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      fieldErrors: { storeSlug: 'That address is already taken. Choose another.' },
      organizationCreated: true,
    });
  });

  it('answers a taken business slug on the business field without flagging a created business', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('slug_taken', 'organization'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      fieldErrors: { organizationSlug: 'That address is already taken. Choose another.' },
    });
  });

  it('answers a rejected address (422) on the matching slug field', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('invalid', 'organization'));
    expect((await createStoreAction(NEW)).fieldErrors?.organizationSlug).toBe(
      'That address cannot be used. Choose another.'
    );
  });

  it('tells the user a half-finished setup is saved and flags it for resume mode', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('unavailable', 'store', 'o1'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      error:
        'Your business was created but the store was not. Submit again to finish setting it up.',
      organizationCreated: true,
    });
  });

  it('gives the plan-limit message', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('limit', 'organization'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      error: 'Your plan does not allow another store.',
    });
  });

  it('gives the already-onboarded message', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('already_onboarded', 'organization'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      error: 'You already have a store. Open your dashboard.',
    });
  });

  it('gives a generic message for an unavailable backend before anything was created', async () => {
    mocks.createOrganizationWithStore.mockResolvedValue(fail('unavailable', 'organization'));
    expect(await createStoreAction(NEW)).toEqual({
      success: false,
      error: 'We could not set up your store. Please try again.',
    });
  });

  it('does not leak a thrown error message', async () => {
    mocks.createOrganizationWithStore.mockRejectedValue(new Error('secret db url'));
    const result = await createStoreAction(NEW);
    expect(result).toEqual({
      success: false,
      error: 'We could not set up your store. Please try again.',
    });
    expect(JSON.stringify(mocks.loggerError.mock.calls)).not.toMatch(/secret/);
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
    expect(await getStoreStatusAction('bad id!')).toEqual({ success: false, notFound: true });
    expect(mocks.fetchStoreStatus).not.toHaveBeenCalled();
  });

  it('answers the unauthorized code without a verified session', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);
    expect(await getStoreStatusAction(STORE_ID)).toEqual({ success: false, code: 'unauthorized' });
    expect(mocks.fetchStoreStatus).not.toHaveBeenCalled();
  });

  it('answers not found for a store that is not the caller own', async () => {
    mocks.fetchStoreStatus.mockResolvedValue({ success: false, reason: 'not_found' });
    expect(await getStoreStatusAction(STORE_ID)).toEqual({ success: false, notFound: true });
  });

  it('answers a retryable error, not unauthorized, when the session check itself fails', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(new Error('firebase down'));
    expect(await getStoreStatusAction(STORE_ID)).toEqual({
      success: false,
      error: 'Could not check your store. Please try again.',
    });
  });

  it('answers a retryable error when the backend is unavailable', async () => {
    mocks.fetchStoreStatus.mockResolvedValue({ success: false, reason: 'unavailable' });
    expect(await getStoreStatusAction(STORE_ID)).toEqual({
      success: false,
      error: 'Could not check your store. Please try again.',
    });
  });
});
