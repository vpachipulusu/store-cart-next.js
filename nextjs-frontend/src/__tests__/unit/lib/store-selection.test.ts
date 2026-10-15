/** KAN-61: the selected store is only ever one the user may open; anything else falls back to the first store. */
import { describe, expect, it } from 'vitest';
import { isStoreId, resolveStoreSelection, type MerchantStore } from '@/lib/stores/selection';

const store = (id: string, name: string): MerchantStore => ({
  id,
  name,
  slug: name.toLowerCase(),
  status: 'ACTIVE',
  organizationId: '11111111-1111-4111-8111-111111111111',
  organizationName: 'Org',
});

const FIRST = store('tz4a98xxat96iws9zmbrgj3a', 'First');
const SECOND = store('pfh0haxfpzowht3oi213cqos', 'Second');

describe('resolveStoreSelection', () => {
  it('selects the requested store when the user may access it', () => {
    expect(resolveStoreSelection([FIRST, SECOND], SECOND.id).selected).toBe(SECOND);
  });

  it('falls back to the first store when the cookie is missing', () => {
    expect(resolveStoreSelection([FIRST, SECOND], undefined).selected).toBe(FIRST);
  });

  it('falls back to the first store when the cookie names a store the user cannot access', () => {
    const foreign = 'ckwdiixuhlkv0ib2d6m3y6hz';
    expect(resolveStoreSelection([FIRST, SECOND], foreign).selected).toBe(FIRST);
  });

  it.each(['', '../../etc/passwd', "x' OR 1=1 --", 'a'.repeat(65)])(
    'ignores the malformed cookie %j',
    (cookie) => {
      expect(resolveStoreSelection([FIRST, SECOND], cookie).selected).toBe(FIRST);
    }
  );

  it('has no selection when the user has no stores', () => {
    expect(resolveStoreSelection([], SECOND.id)).toEqual({ stores: [], selected: null });
  });

  it('selects the only store of a one-store user whatever the cookie says', () => {
    expect(resolveStoreSelection([FIRST], SECOND.id).selected).toBe(FIRST);
  });
});

describe('isStoreId', () => {
  it('accepts cuid2 and UUID ids and rejects anything else', () => {
    expect(isStoreId(FIRST.id)).toBe(true);
    expect(isStoreId('3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b')).toBe(true);
    expect(isStoreId('has space')).toBe(false);
    expect(isStoreId(42)).toBe(false);
    expect(isStoreId(null)).toBe(false);
  });
});
