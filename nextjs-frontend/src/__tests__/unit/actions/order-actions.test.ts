// @vitest-environment node
/** KAN-79: the fulfil action validates input, takes the store from the server, and curates errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  fulfilStoreOrder: vi.fn(),
}));

vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api/orders', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/orders')>('@/lib/api/orders');
  return { ...actual, fulfilStoreOrder: mocks.fulfilStoreOrder };
});

import { fulfilOrderAction } from '@/app/actions/order-actions';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

const STORE = 'store1';
const ORDER = 'order1';
const order = { id: ORDER, status: 'fulfilled' };

describe('fulfilOrderAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: { id: STORE, name: 'Shop' },
    });
    mocks.fulfilStoreOrder.mockResolvedValue({ success: true, data: order });
  });

  it('fulfils with the store from the server, trims input and turns a blank carrier into null', async () => {
    const result = await fulfilOrderAction(ORDER, { trackingNumber: '  T-1 ', carrier: '   ' });

    expect(result).toEqual({ success: true, data: order });
    expect(mocks.fulfilStoreOrder).toHaveBeenCalledWith(STORE, ORDER, {
      trackingNumber: 'T-1',
      carrier: null,
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/orders');
    expect(mocks.revalidatePath).toHaveBeenCalledWith(`/dashboard/orders/${ORDER}`);
  });

  it('passes a carrier through', async () => {
    await fulfilOrderAction(ORDER, { trackingNumber: 'T-1', carrier: 'UPS' });

    expect(mocks.fulfilStoreOrder).toHaveBeenCalledWith(STORE, ORDER, {
      trackingNumber: 'T-1',
      carrier: 'UPS',
    });
  });

  it.each([
    ['empty tracking', { trackingNumber: '   ' }, 'trackingNumber'],
    ['long tracking', { trackingNumber: 'x'.repeat(101) }, 'trackingNumber'],
    ['control characters', { trackingNumber: 'a\nb' }, 'trackingNumber'],
    ['long carrier', { trackingNumber: 'T-1', carrier: 'y'.repeat(101) }, 'carrier'],
  ])('rejects %s without calling the backend', async (_name, input, field) => {
    const result = await fulfilOrderAction(ORDER, input);

    expect(result.success).toBe(false);
    expect(result.fieldErrors).toHaveProperty(field);
    expect(mocks.fulfilStoreOrder).not.toHaveBeenCalled();
  });

  it('rejects an order id with unexpected characters', async () => {
    const result = await fulfilOrderAction('../x', { trackingNumber: 'T-1' });

    expect(result).toEqual({ success: false, error: 'That order could not be found.' });
    expect(mocks.fulfilStoreOrder).not.toHaveBeenCalled();
  });

  it('explains an unavailable store list and a missing selection', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValueOnce({ available: false });
    const unavailable = await fulfilOrderAction(ORDER, { trackingNumber: 'T-1' });
    mocks.getCurrentStoreSelection.mockResolvedValueOnce({
      available: true,
      stores: [],
      selected: null,
    });
    const none = await fulfilOrderAction(ORDER, { trackingNumber: 'T-1' });

    expect(unavailable).toMatchObject({ success: false, error: STORES_UNAVAILABLE_MESSAGE });
    expect(none).toMatchObject({
      success: false,
      error: 'Select a store before managing orders.',
    });
    expect(mocks.fulfilStoreOrder).not.toHaveBeenCalled();
  });

  it('shows a curated 409 and hides the text of other failures', async () => {
    mocks.fulfilStoreOrder.mockResolvedValueOnce({
      success: false,
      error: 'Only a paid order can be fulfilled',
      status: 409,
    });
    const conflict = await fulfilOrderAction(ORDER, { trackingNumber: 'T-1' });
    mocks.fulfilStoreOrder.mockResolvedValueOnce({
      success: false,
      error: 'secret backend detail',
      status: 500,
    });
    const broken = await fulfilOrderAction(ORDER, { trackingNumber: 'T-1' });

    expect(conflict).toMatchObject({ error: 'Only a paid order can be fulfilled' });
    expect(broken.success).toBe(false);
    expect(JSON.stringify(broken)).not.toContain('secret backend detail');
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });
});
