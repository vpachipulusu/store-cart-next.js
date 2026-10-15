// @vitest-environment node
/** KAN-61: selecting a store only stores an id the backend lists for the caller. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  fetchMerchantStores: vi.fn(),
  cookieSet: vi.fn(),
  revalidatePath: vi.fn(),
}));

vi.mock('next/headers', () => ({ cookies: async () => ({ set: mocks.cookieSet }) }));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/api/stores', () => ({ fetchMerchantStores: mocks.fetchMerchantStores }));

import { selectStoreAction } from '@/app/actions/store-actions';
import { STORE_NOT_AVAILABLE_MESSAGE, STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

const OWN = 'tz4a98xxat96iws9zmbrgj3a';
const FOREIGN = 'ckwdiixuhlkv0ib2d6m3y6hz';

describe('selectStoreAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchMerchantStores.mockResolvedValue({ success: true, data: [{ id: OWN }] });
  });

  it('sets an httpOnly cookie for a store the user may open', async () => {
    expect(await selectStoreAction(OWN)).toEqual({ success: true });
    expect(mocks.cookieSet).toHaveBeenCalledWith(
      'selected-store',
      OWN,
      expect.objectContaining({ httpOnly: true, sameSite: 'lax', path: '/' })
    );
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard', 'layout');
  });

  it('rejects a store the user cannot open without setting the cookie', async () => {
    expect(await selectStoreAction(FOREIGN)).toEqual({
      success: false,
      error: STORE_NOT_AVAILABLE_MESSAGE,
    });
    expect(mocks.cookieSet).not.toHaveBeenCalled();
  });

  it('rejects a malformed id without calling the backend', async () => {
    expect((await selectStoreAction('bad id!')).success).toBe(false);
    expect(mocks.fetchMerchantStores).not.toHaveBeenCalled();
  });

  it('fails closed when the backend cannot list stores', async () => {
    mocks.fetchMerchantStores.mockResolvedValue({ success: false, error: 'Backend unavailable' });
    expect(await selectStoreAction(OWN)).toEqual({
      success: false,
      error: STORES_UNAVAILABLE_MESSAGE,
    });
    expect(mocks.cookieSet).not.toHaveBeenCalled();
  });
});
