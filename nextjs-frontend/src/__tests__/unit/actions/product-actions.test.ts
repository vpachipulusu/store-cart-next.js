// @vitest-environment node
/** KAN-73: product actions validate input, take the store from the server, and curate errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  revalidateTag: vi.fn(),
  createStoreProduct: vi.fn(),
  updateStoreProduct: vi.fn(),
  deleteStoreProduct: vi.fn(),
  addProductVariant: vi.fn(),
  updateProductVariant: vi.fn(),
  deleteProductVariant: vi.fn(),
  deleteProductImage: vi.fn(),
}));

vi.mock('next/cache', () => ({
  revalidatePath: mocks.revalidatePath,
  revalidateTag: mocks.revalidateTag,
}));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api/products', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/products')>('@/lib/api/products');
  return {
    ...actual,
    createStoreProduct: mocks.createStoreProduct,
    updateStoreProduct: mocks.updateStoreProduct,
    deleteStoreProduct: mocks.deleteStoreProduct,
    addProductVariant: mocks.addProductVariant,
    updateProductVariant: mocks.updateProductVariant,
    deleteProductVariant: mocks.deleteProductVariant,
    deleteProductImage: mocks.deleteProductImage,
  };
});

import {
  addVariantAction,
  createProductAction,
  deleteImageAction,
  deleteProductAction,
  deleteVariantAction,
  updateProductAction,
  updateVariantAction,
} from '@/app/actions/product-actions';
import { STORES_UNAVAILABLE_MESSAGE } from '@/lib/stores/selection';

const STORE = 'store1';
const PRODUCT = 'prod1';
const product = { id: PRODUCT, title: 'Tee' };

const variant = {
  sku: 'TEE-1',
  priceMinor: 1250,
  compareAtPriceMinor: null,
  weightGrams: null,
  stock: 2,
};

const details = {
  title: 'Tee',
  slug: null,
  description: null,
  status: 'draft' as const,
  categoryIds: ['cat1'],
};

describe('product actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: { id: STORE, name: 'Shop', slug: 'shop' },
    });
    for (const key of [
      'createStoreProduct',
      'updateStoreProduct',
      'addProductVariant',
      'updateProductVariant',
      'deleteProductVariant',
      'deleteProductImage',
    ] as const) {
      mocks[key].mockResolvedValue({ success: true, data: product });
    }
    mocks.deleteStoreProduct.mockResolvedValue({ success: true, data: undefined });
  });

  describe('createProductAction', () => {
    it('maps the form shape to the API body and revalidates the list', async () => {
      const result = await createProductAction({
        ...details,
        slug: 'tee',
        options: [{ name: 'Size', values: ['S'] }],
        variants: [{ ...variant, options: { Size: 'S' } }],
      });

      expect(result).toEqual({ success: true, data: product });
      expect(mocks.createStoreProduct).toHaveBeenCalledWith(STORE, {
        title: 'Tee',
        slug: 'tee',
        description: null,
        status: 'draft',
        category_ids: ['cat1'],
        options: [{ name: 'Size', values: ['S'] }],
        variants: [
          {
            sku: 'TEE-1',
            price_minor: 1250,
            compare_at_price_minor: null,
            weight_grams: null,
            stock: 2,
            options: { Size: 'S' },
          },
        ],
      });
      expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/products');
      // KAN-75: the store's cached storefront pages expire at once.
      expect(mocks.revalidateTag).toHaveBeenCalledWith('storefront:shop', { expire: 0 });
    });

    it('rejects invalid input with field errors and never calls the backend', async () => {
      const result = await createProductAction({
        ...details,
        title: '',
        options: [],
        variants: [],
      });

      expect(result.success).toBe(false);
      expect(result.fieldErrors?.title).toBe('Title is required');
      expect(mocks.createStoreProduct).not.toHaveBeenCalled();
    });

    it('fails closed when the stores cannot be loaded', async () => {
      mocks.getCurrentStoreSelection.mockResolvedValue({ available: false, error: 'boom' });
      const result = await createProductAction({ ...details, options: [], variants: [variant] });
      expect(result).toMatchObject({ success: false, error: STORES_UNAVAILABLE_MESSAGE });
      expect(mocks.createStoreProduct).not.toHaveBeenCalled();
    });

    it('asks to select a store when the user has none', async () => {
      mocks.getCurrentStoreSelection.mockResolvedValue({
        available: true,
        stores: [],
        selected: null,
      });
      const result = await createProductAction({ ...details, options: [], variants: [variant] });
      expect(result.success).toBe(false);
      expect(mocks.createStoreProduct).not.toHaveBeenCalled();
    });

    it('shows the curated 409 text and hides anything from a 500', async () => {
      mocks.createStoreProduct.mockResolvedValueOnce({
        success: false,
        error: 'Slug already exists',
        status: 409,
      });
      const conflict = await createProductAction({ ...details, options: [], variants: [variant] });
      expect(conflict).toMatchObject({ success: false, error: 'Slug already exists' });

      mocks.createStoreProduct.mockResolvedValueOnce({
        success: false,
        error: 'psycopg2 connection string leaked',
        status: 500,
      });
      const failure = await createProductAction({ ...details, options: [], variants: [variant] });
      expect(failure.error).not.toContain('psycopg2');
    });
  });

  describe('updateProductAction', () => {
    it('sends a changed slug and clears an empty description with null', async () => {
      await updateProductAction(PRODUCT, { ...details, slug: 'new-slug' });
      expect(mocks.updateStoreProduct).toHaveBeenCalledWith(STORE, PRODUCT, {
        title: 'Tee',
        slug: 'new-slug',
        description: null,
        status: 'draft',
        category_ids: ['cat1'],
      });
      expect(mocks.revalidatePath).toHaveBeenCalledWith(`/dashboard/products/${PRODUCT}`);
    });

    it('leaves the slug out when it is empty', async () => {
      await updateProductAction(PRODUCT, details);
      expect(mocks.updateStoreProduct.mock.calls[0][2]).not.toHaveProperty('slug');
    });

    it('rejects a malformed product id without calling the backend', async () => {
      const result = await updateProductAction('../etc', details);
      expect(result.success).toBe(false);
      expect(mocks.updateStoreProduct).not.toHaveBeenCalled();
    });

    it('rejects an invalid slug', async () => {
      const result = await updateProductAction(PRODUCT, { ...details, slug: 'Bad Slug' });
      expect(result.fieldErrors?.slug).toBeDefined();
      expect(mocks.updateStoreProduct).not.toHaveBeenCalled();
    });

    it('relays a curated 422', async () => {
      mocks.updateStoreProduct.mockResolvedValue({
        success: false,
        error: 'Unknown category',
        status: 422,
      });
      expect(await updateProductAction(PRODUCT, details)).toMatchObject({
        success: false,
        error: 'Unknown category',
      });
    });
  });

  describe('deleteProductAction', () => {
    it('deletes in the current store and revalidates', async () => {
      expect(await deleteProductAction(PRODUCT)).toEqual({
        success: true,
        data: { deleted: true },
      });
      expect(mocks.deleteStoreProduct).toHaveBeenCalledWith(STORE, PRODUCT);
      expect(mocks.revalidatePath).toHaveBeenCalledWith('/dashboard/products');
    });

    it('reports a product that is gone', async () => {
      mocks.deleteStoreProduct.mockResolvedValue({
        success: false,
        error: 'Product not found',
        status: 404,
      });
      expect(await deleteProductAction(PRODUCT)).toMatchObject({
        success: false,
        error: 'Product not found',
      });
    });

    it('rejects a malformed id', async () => {
      expect((await deleteProductAction('a b')).success).toBe(false);
      expect(mocks.deleteStoreProduct).not.toHaveBeenCalled();
    });
  });

  describe('variant actions', () => {
    it('adds a variant with its options', async () => {
      await addVariantAction(PRODUCT, { ...variant, options: { Size: 'M' } });
      expect(mocks.addProductVariant).toHaveBeenCalledWith(
        STORE,
        PRODUCT,
        expect.objectContaining({ sku: 'TEE-1', price_minor: 1250, options: { Size: 'M' } })
      );
    });

    it('rejects a compare-at price below the price before the backend', async () => {
      const result = await addVariantAction(PRODUCT, { ...variant, compareAtPriceMinor: 100 });
      expect(result.fieldErrors?.compareAtPriceMinor).toBeDefined();
      expect(mocks.addProductVariant).not.toHaveBeenCalled();
    });

    it('updates a variant without sending options', async () => {
      await updateVariantAction(PRODUCT, 'v1', { ...variant, options: { Size: 'M' } });
      expect(mocks.updateProductVariant.mock.calls[0][3]).toEqual({
        sku: 'TEE-1',
        price_minor: 1250,
        compare_at_price_minor: null,
        weight_grams: null,
        stock: 2,
      });
    });

    it('rejects malformed variant ids', async () => {
      expect((await updateVariantAction(PRODUCT, 'x/y', variant)).success).toBe(false);
      expect((await deleteVariantAction(PRODUCT, '')).success).toBe(false);
      expect(mocks.updateProductVariant).not.toHaveBeenCalled();
      expect(mocks.deleteProductVariant).not.toHaveBeenCalled();
    });

    it('relays the last-variant rule as a curated 422', async () => {
      mocks.deleteProductVariant.mockResolvedValue({
        success: false,
        error: 'A product needs at least one variant',
        status: 422,
      });
      expect(await deleteVariantAction(PRODUCT, 'v1')).toMatchObject({
        success: false,
        error: 'A product needs at least one variant',
      });
    });
  });

  describe('deleteImageAction', () => {
    it('removes the image row and returns the product', async () => {
      expect(await deleteImageAction(PRODUCT, 'i1')).toEqual({ success: true, data: product });
      expect(mocks.deleteProductImage).toHaveBeenCalledWith(STORE, PRODUCT, 'i1');
    });

    it('rejects a malformed image id', async () => {
      expect((await deleteImageAction(PRODUCT, '../')).success).toBe(false);
      expect(mocks.deleteProductImage).not.toHaveBeenCalled();
    });
  });

  describe('storefront cache (KAN-75)', () => {
    it.each([
      ['update', () => updateProductAction(PRODUCT, details)],
      ['delete', () => deleteProductAction(PRODUCT)],
      ['add variant', () => addVariantAction(PRODUCT, { ...variant, options: {} })],
      ['update variant', () => updateVariantAction(PRODUCT, 'v1', { ...variant, options: {} })],
      ['delete variant', () => deleteVariantAction(PRODUCT, 'v1')],
      ['delete image', () => deleteImageAction(PRODUCT, 'i1')],
    ])('%s expires the pages of the selected store by slug, not id', async (_name, run) => {
      await run();

      expect(mocks.revalidateTag).toHaveBeenCalledTimes(1);
      expect(mocks.revalidateTag).toHaveBeenCalledWith('storefront:shop', { expire: 0 });
    });

    it('leaves the cache alone when the backend refuses the change', async () => {
      mocks.updateStoreProduct.mockResolvedValue({ success: false, error: 'Nope', status: 422 });

      await updateProductAction(PRODUCT, details);

      expect(mocks.revalidateTag).not.toHaveBeenCalled();
    });
  });
});
