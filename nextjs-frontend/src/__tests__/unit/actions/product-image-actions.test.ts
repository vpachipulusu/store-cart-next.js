// @vitest-environment node
/** KAN-249: image actions validate type, size and key prefix on the server and curate errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  presignProductImage: vi.fn(),
  addProductImage: vi.fn(),
  warn: vi.fn(),
}));

vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
}));
vi.mock('@/lib/logger', () => ({ logger: { warn: mocks.warn, error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api/products', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/products')>('@/lib/api/products');
  return {
    ...actual,
    presignProductImage: mocks.presignProductImage,
    addProductImage: mocks.addProductImage,
  };
});

import { addImageAction, presignImageUploadAction } from '@/app/actions/product-actions';
import { MAX_IMAGE_BYTES } from '@/lib/products/image-upload';

const STORE = 'store1';
const PRODUCT = 'prod1';
const KEY = `stores/${STORE}/img1.png`;
const URL_WITH_SECRET = 'https://r2.example/x.png?X-Amz-Signature=secret';
const ticket = { uploadUrl: URL_WITH_SECRET, headers: { 'Content-Type': 'image/png' }, key: KEY };
const png = { contentType: 'image/png', sizeBytes: 1000 };

function selectStore() {
  mocks.getCurrentStoreSelection.mockResolvedValue({
    available: true,
    stores: [],
    selected: { id: STORE, name: 'Shop' },
  });
}

describe('presignImageUploadAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    selectStore();
    mocks.presignProductImage.mockResolvedValue({ success: true, data: ticket });
  });

  it('presigns for the selected store and returns the ticket', async () => {
    expect(await presignImageUploadAction(PRODUCT, png)).toEqual({ success: true, data: ticket });
    expect(mocks.presignProductImage).toHaveBeenCalledWith(STORE, png);
  });

  it.each([
    [{ contentType: 'image/svg+xml', sizeBytes: 10 }, /JPEG, PNG or WebP/],
    [{ contentType: 'image/png', sizeBytes: MAX_IMAGE_BYTES + 1 }, /larger than 10 MB/],
    [{ contentType: 'image/png', sizeBytes: 0 }, /empty/],
  ])('rejects %j before any backend call', async (input, message) => {
    const result = await presignImageUploadAction(PRODUCT, input);
    expect(result.success).toBe(false);
    expect(result.error).toMatch(message);
    expect(mocks.presignProductImage).not.toHaveBeenCalled();
  });

  it('rejects a bad product id', async () => {
    const result = await presignImageUploadAction('../x', png);
    expect(result.success).toBe(false);
    expect(mocks.presignProductImage).not.toHaveBeenCalled();
  });

  it('asks for a store when none is selected', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });
    const result = await presignImageUploadAction(PRODUCT, png);
    expect(result.error).toMatch(/select a store/i);
  });

  it('shows curated backend text and a fixed message for other failures', async () => {
    mocks.presignProductImage.mockResolvedValueOnce({
      success: false,
      error: 'Image size is not allowed',
      status: 422,
    });
    expect((await presignImageUploadAction(PRODUCT, png)).error).toBe('Image size is not allowed');

    mocks.presignProductImage.mockResolvedValueOnce({
      success: false,
      error: 'boom: secret detail',
      status: 500,
    });
    expect((await presignImageUploadAction(PRODUCT, png)).error).toBe(
      'The request failed. Please try again.'
    );
  });

  it.each([
    ['a foreign store prefix', { ...ticket, key: 'stores/other/img1.png' }],
    ['a non-https URL', { ...ticket, uploadUrl: 'http://evil.example/x.png?sig=1' }],
    ['a malformed URL', { ...ticket, uploadUrl: 'not a url' }],
  ])('refuses a backend ticket with %s and logs no URL', async (_name, bad) => {
    mocks.presignProductImage.mockResolvedValue({ success: true, data: bad });
    const result = await presignImageUploadAction(PRODUCT, png);
    expect(result.success).toBe(false);
    expect(JSON.stringify(mocks.warn.mock.calls)).not.toContain('evil.example');
  });

  it('allows plain http only for localhost', async () => {
    mocks.presignProductImage.mockResolvedValue({
      success: true,
      data: { ...ticket, uploadUrl: 'http://localhost:9000/x.png?sig=1' },
    });
    expect((await presignImageUploadAction(PRODUCT, png)).success).toBe(true);
  });
});

describe('addImageAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    selectStore();
    mocks.addProductImage.mockResolvedValue({ success: true, data: { id: PRODUCT } });
  });

  it('registers the image with trimmed alt text and revalidates the editor', async () => {
    const result = await addImageAction(PRODUCT, { storageKey: KEY, altText: ' Front ' });

    expect(result).toEqual({ success: true, data: { id: PRODUCT } });
    expect(mocks.addProductImage).toHaveBeenCalledWith(STORE, PRODUCT, {
      storage_key: KEY,
      alt_text: 'Front',
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith(`/dashboard/products/${PRODUCT}`);
  });

  it('sends null alt text when blank', async () => {
    await addImageAction(PRODUCT, { storageKey: KEY, altText: '' });
    expect(mocks.addProductImage).toHaveBeenCalledWith(STORE, PRODUCT, {
      storage_key: KEY,
      alt_text: null,
    });
  });

  it('rejects a key outside the selected store before calling the backend', async () => {
    const result = await addImageAction(PRODUCT, { storageKey: 'stores/other/img1.png' });
    expect(result.error).toMatch(/does not belong/i);
    expect(mocks.addProductImage).not.toHaveBeenCalled();
  });

  it('returns a field error for over-long alt text', async () => {
    const result = await addImageAction(PRODUCT, { storageKey: KEY, altText: 'a'.repeat(501) });
    expect(result.success).toBe(false);
    expect(result.fieldErrors?.altText).toMatch(/500/);
    expect(mocks.addProductImage).not.toHaveBeenCalled();
  });

  it('curates backend failures', async () => {
    mocks.addProductImage.mockResolvedValue({
      success: false,
      error: 'Image is already attached',
      status: 409,
    });
    expect((await addImageAction(PRODUCT, { storageKey: KEY })).error).toBe(
      'Image is already attached'
    );
  });
});
