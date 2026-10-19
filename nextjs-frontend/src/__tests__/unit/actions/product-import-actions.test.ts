// @vitest-environment node
/** KAN-74: the import action validates the file, refuses a store mismatch and curates backend failures. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  importStoreProducts: vi.fn(),
  warn: vi.fn(),
}));

vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { warn: mocks.warn, error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api/products', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/products')>('@/lib/api/products');
  return { ...actual, importStoreProducts: mocks.importStoreProducts };
});

import { importProductsAction } from '@/app/actions/product-import-actions';
import {
  MAX_IMPORT_BYTES,
  NO_FILE_MESSAGE,
  TOO_LARGE_MESSAGE,
  WRONG_TYPE_MESSAGE,
} from '@/lib/products/csv-import';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

const STORE = 'store1';
const CHANGED = 'The selected store changed. Reload the page and try again.';
const outcome = { imported: 2, errors: [], truncated: false };
const csv = () => new File(['title,sku,price_minor\nA,A-1,1\n'], 'p.csv', { type: 'text/csv' });

function form(file: File | string | null = csv()) {
  const data = new FormData();
  if (file !== null) data.append('file', file);
  return data;
}

function selectStore(id = STORE) {
  mocks.getCurrentStoreSelection.mockResolvedValue({
    available: true,
    stores: [],
    selected: { id, name: 'Shop' },
  });
}

describe('importProductsAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    selectStore();
    mocks.importStoreProducts.mockResolvedValue({ success: true, data: outcome });
  });

  it('imports into the selected store and refreshes the list', async () => {
    const result = await importProductsAction(STORE, form());

    expect(result).toEqual({ success: true, data: outcome });
    expect(mocks.importStoreProducts).toHaveBeenCalledWith(STORE, expect.any(File));
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/products');
  });

  it('returns row problems as data and does not refresh when nothing was imported', async () => {
    const rejected = {
      imported: 0,
      errors: [{ row: 3, column: 'sku', message: 'SKU is already in use' }],
      truncated: false,
    };
    mocks.importStoreProducts.mockResolvedValue({ success: true, data: rejected });

    expect(await importProductsAction(STORE, form())).toEqual({ success: true, data: rejected });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it('refuses a rendered store id that is no longer the selected store', async () => {
    selectStore('store2');

    expect(await importProductsAction(STORE, form())).toEqual({ success: false, error: CHANGED });
    expect(mocks.importStoreProducts).not.toHaveBeenCalled();
  });

  it('refuses a malformed store id before reading the selection', async () => {
    expect(await importProductsAction('../x', form())).toEqual({ success: false, error: CHANGED });
    expect(mocks.getCurrentStoreSelection).not.toHaveBeenCalled();
  });

  it.each([
    ['no file', null, NO_FILE_MESSAGE],
    ['text instead of a file', 'title,sku', NO_FILE_MESSAGE],
    ['a non-csv name', new File(['x'], 'p.xlsx', { type: 'text/csv' }), WRONG_TYPE_MESSAGE],
    [
      'an oversized file',
      new File([new Uint8Array(MAX_IMPORT_BYTES + 1)], 'p.csv', { type: 'text/csv' }),
      TOO_LARGE_MESSAGE,
    ],
  ])('rejects %s before any backend call', async (_name, file, message) => {
    expect(await importProductsAction(STORE, form(file))).toEqual({
      success: false,
      error: message,
    });
    expect(mocks.importStoreProducts).not.toHaveBeenCalled();
  });

  it('asks for a store when none is selected', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });

    const result = await importProductsAction(STORE, form());

    expect(result.success).toBe(false);
    expect(result.error).toMatch(/Select a store/);
  });

  it('reports a store list that could not load', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({ available: false });

    expect(await importProductsAction(STORE, form())).toEqual({
      success: false,
      error: STORES_UNAVAILABLE_MESSAGE,
    });
  });

  it.each([
    [{ success: false, error: 'Store not found', status: 404 }, 'Store not found'],
    [
      { success: false, error: 'x', status: 403 },
      'You do not have permission to do that in this store.',
    ],
    [{ success: false, error: 'The file is larger than 1000 KB', status: 413 }, TOO_LARGE_MESSAGE],
    [
      { success: false, error: 'Backend unavailable' },
      'Products could not be reached. Please try again.',
    ],
  ])('curates the backend failure %j', async (failure, message) => {
    mocks.importStoreProducts.mockResolvedValue(failure);

    expect(await importProductsAction(STORE, form())).toEqual({ success: false, error: message });
    expect(mocks.warn).toHaveBeenCalledWith('Product import failed', {
      status: 'status' in failure ? failure.status : undefined,
    });
  });
});
