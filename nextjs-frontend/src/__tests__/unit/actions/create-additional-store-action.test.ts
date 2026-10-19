// @vitest-environment node
/**
 * KAN-254: "New store" from the dashboard. The organisation comes from the server-validated store selection,
 * never from the browser; input uses the onboarding validation; a plan limit is the upgrade message.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getVerifiedSessionClaims: vi.fn(),
  getCurrentStoreSelection: vi.fn(),
  createStoreInOrganization: vi.fn(),
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
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/api/onboarding', () => ({
  createOrganizationWithStore: vi.fn(),
  fetchStoreStatus: vi.fn(),
  requestProvisioningRetry: vi.fn(),
  createStoreInOrganization: mocks.createStoreInOrganization,
}));

import { createAdditionalStoreAction } from '@/app/actions/onboarding-actions';
import { NEW_STORE_FORBIDDEN_MESSAGE, NEW_STORE_LIMIT_MESSAGE } from '@/lib/onboarding/schema';

const INPUT = { storeName: 'Second Shop', storeSlug: 'second-shop' };
const SELECTED = {
  id: 'tz4a98xxat96iws9zmbrgj3a',
  name: 'First',
  slug: 'first',
  status: 'ACTIVE',
  organizationId: 'org-own',
  organizationName: 'Acme',
};
const GENERIC = 'We could not set up your store. Please try again.';

describe('createAdditionalStoreAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedSessionClaims.mockResolvedValue({ uid: 'u1' });
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [SELECTED],
      selected: SELECTED,
    });
    mocks.createStoreInOrganization.mockResolvedValue({
      success: true,
      storeId: 'pfh0haxfpzowht3oi213cqos',
      name: 'Second Shop',
      status: 'PROVISIONING',
    });
  });

  it('creates the store in the selected organisation and returns its id, name and status', async () => {
    const result = await createAdditionalStoreAction(INPUT);

    expect(result).toEqual({
      success: true,
      data: { storeId: 'pfh0haxfpzowht3oi213cqos', name: 'Second Shop', status: 'PROVISIONING' },
    });
    expect(mocks.createStoreInOrganization).toHaveBeenCalledWith('org-own', INPUT);
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard', 'layout');
  });

  it('ignores an organisation id sent by the browser', async () => {
    await createAdditionalStoreAction({ ...INPUT, organizationId: 'org-someone-else' } as never);
    expect(mocks.createStoreInOrganization).toHaveBeenCalledWith('org-own', INPUT);
  });

  it('trims the input like onboarding does', async () => {
    await createAdditionalStoreAction({ storeName: '  Second Shop ', storeSlug: ' second-shop ' });
    expect(mocks.createStoreInOrganization).toHaveBeenCalledWith('org-own', INPUT);
  });

  it.each([
    [{ storeName: '', storeSlug: 'second-shop' }, 'storeName', 'Store name is required'],
    [
      { storeName: 'Shop', storeSlug: 'Bad Slug' },
      'storeSlug',
      'Store address can use lowercase letters, numbers and single hyphens only',
    ],
    [
      { storeName: 'Shop', storeSlug: 'ab' },
      'storeSlug',
      'Store address must be at least 3 characters',
    ],
  ])('rejects invalid input with the onboarding field errors', async (input, field, message) => {
    const result = await createAdditionalStoreAction(input);
    expect(result).toEqual({ success: false, fieldErrors: { [field]: message } });
    expect(mocks.createStoreInOrganization).not.toHaveBeenCalled();
  });

  it('rejects a non-object submission without calling the backend', async () => {
    expect(await createAdditionalStoreAction(null as never)).toEqual({
      success: false,
      error: GENERIC,
    });
    expect(mocks.createStoreInOrganization).not.toHaveBeenCalled();
  });

  it('shows the taken-address message on the store address field', async () => {
    mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason: 'slug_taken' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      fieldErrors: { storeSlug: 'That address is already taken. Choose another.' },
    });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it('shows the unusable-address message for a reserved address', async () => {
    mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason: 'invalid' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      fieldErrors: { storeSlug: 'That address cannot be used. Choose another.' },
    });
  });

  it('returns the plan upgrade message when the store limit is reached', async () => {
    const limitMessage = 'The Free plan allows 1 store. Upgrade your plan to add more.';
    mocks.createStoreInOrganization.mockResolvedValue({
      success: false,
      reason: 'limit',
      limitMessage,
    });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      limitReached: true,
      error: limitMessage,
    });
  });

  it('falls back to a fixed upgrade message when the plan wording is unknown', async () => {
    mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason: 'limit' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      limitReached: true,
      error: NEW_STORE_LIMIT_MESSAGE,
    });
    expect(NEW_STORE_LIMIT_MESSAGE).toContain('Upgrade your plan to add more.');
  });

  it('tells a member without the right role that only an owner or admin can add a store', async () => {
    mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason: 'forbidden' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      error: NEW_STORE_FORBIDDEN_MESSAGE,
    });
  });

  it('returns the unauthorized code when the backend rejects the session', async () => {
    mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason: 'unauthorized' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      code: 'unauthorized',
    });
  });

  it.each(['not_found', 'unavailable'])(
    'logs %s and returns the generic message',
    async (reason) => {
      mocks.createStoreInOrganization.mockResolvedValue({ success: false, reason });
      expect(await createAdditionalStoreAction(INPUT)).toEqual({ success: false, error: GENERIC });
      expect(mocks.loggerError).toHaveBeenCalledWith('New store failed', { reason });
    }
  );

  it('returns the generic message when the call throws', async () => {
    mocks.createStoreInOrganization.mockRejectedValue(new TypeError('fetch failed'));
    expect(await createAdditionalStoreAction(INPUT)).toEqual({ success: false, error: GENERIC });
    expect(mocks.loggerError).toHaveBeenCalledWith('New store error', { errorName: 'TypeError' });
  });

  it('needs a signed-in session and calls nothing without one', async () => {
    mocks.getVerifiedSessionClaims.mockResolvedValue(null);
    expect(await createAdditionalStoreAction(INPUT)).toEqual({
      success: false,
      code: 'unauthorized',
    });
    expect(mocks.getCurrentStoreSelection).not.toHaveBeenCalled();
    expect(mocks.createStoreInOrganization).not.toHaveBeenCalled();
  });

  it('returns the generic message when the session check itself fails', async () => {
    mocks.getVerifiedSessionClaims.mockRejectedValue(new Error('outage'));
    expect(await createAdditionalStoreAction(INPUT)).toEqual({ success: false, error: GENERIC });
  });

  it('does not create a store when the stores cannot be loaded', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({ available: false, error: 'x' });
    expect(await createAdditionalStoreAction(INPUT)).toEqual({ success: false, error: GENERIC });
    expect(mocks.createStoreInOrganization).not.toHaveBeenCalled();
  });

  it('sends a user without any store to onboarding instead', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });
    const result = await createAdditionalStoreAction(INPUT);
    expect(result).toEqual({
      success: false,
      error: 'Set up your first store before adding another.',
    });
    expect(mocks.createStoreInOrganization).not.toHaveBeenCalled();
  });
});
