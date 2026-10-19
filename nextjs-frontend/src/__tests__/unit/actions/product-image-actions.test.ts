// @vitest-environment node
/** KAN-249: image actions validate type, size and key prefix on the server and curate errors. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getCurrentStoreSelection: vi.fn(),
  revalidatePath: vi.fn(),
  revalidateTag: vi.fn(),
  presignProductImage: vi.fn(),
  addProductImage: vi.fn(),
  warn: vi.fn(),
}));

vi.mock('next/cache', () => ({
  revalidatePath: mocks.revalidatePath,
  revalidateTag: mocks.revalidateTag,
}));
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
    selected: { id: STORE, name: 'Shop', slug: 'shop' },
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
    ['credentials in the URL', { ...ticket, uploadUrl: 'https://user:pw@r2.example/x.png?sig=1' }],
  ])('refuses a backend ticket with %s and logs no URL', async (_name, bad) => {
    mocks.presignProductImage.mockResolvedValue({ success: true, data: bad });
    const result = await presignImageUploadAction(PRODUCT, png);
    expect(result).toEqual({ success: false, error: 'The request failed. Please try again.' });
    expect(mocks.warn).toHaveBeenCalledWith('Product action failed', {
      action: 'presign-image',
      status: 502,
    });
    expect(JSON.stringify(mocks.warn.mock.calls)).not.toMatch(/evil|X-Amz|sig=|user:pw/);
  });

  it.each([
    'http://localhost.evil.com/x.png?sig=1',
    'http://localhost@evil.com/x.png?sig=1',
    'http://127.0.0.1.evil.com/x.png?sig=1',
    'ftp://r2.example/x.png',
    'javascript:alert(1)',
  ])('refuses the look-alike or non-http URL %s', async (uploadUrl) => {
    mocks.presignProductImage.mockResolvedValue({ success: true, data: { ...ticket, uploadUrl } });
    expect((await presignImageUploadAction(PRODUCT, png)).success).toBe(false);
  });

  it.each(['http://127.0.0.1:9000/x.png?sig=1', 'http://[::1]:9000/x.png?sig=1'])(
    'allows the loopback test endpoint %s',
    async (uploadUrl) => {
      mocks.presignProductImage.mockResolvedValue({
        success: true,
        data: { ...ticket, uploadUrl },
      });
      expect((await presignImageUploadAction(PRODUCT, png)).success).toBe(true);
    }
  );

  it('strips extra client fields before presigning and does not log a failed presign URL', async () => {
    await presignImageUploadAction(PRODUCT, { ...png, storeId: 'other' } as typeof png);
    expect(mocks.presignProductImage).toHaveBeenCalledWith(STORE, png);

    mocks.presignProductImage.mockResolvedValueOnce({ success: false, error: 'x', status: 500 });
    await presignImageUploadAction(PRODUCT, png);
    expect(JSON.stringify(mocks.warn.mock.calls)).not.toContain('X-Amz');
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

  it('rejects a bad product id and an unavailable or missing store', async () => {
    expect((await addImageAction('../x', { storageKey: KEY })).success).toBe(false);

    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: false,
      stores: [],
      selected: null,
    });
    expect((await addImageAction(PRODUCT, { storageKey: KEY })).success).toBe(false);
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });
    expect((await addImageAction(PRODUCT, { storageKey: KEY })).error).toMatch(/select a store/i);
    expect(mocks.addProductImage).not.toHaveBeenCalled();
  });

  it('rejects control characters in alt text and a non-string key', async () => {
    const alt = await addImageAction(PRODUCT, { storageKey: KEY, altText: 'bad' });
    expect(alt.fieldErrors?.altText).toBeTruthy();
    const key = await addImageAction(PRODUCT, { storageKey: 42 as unknown as string });
    expect(key.success).toBe(false);
    expect(mocks.addProductImage).not.toHaveBeenCalled();
  });

  it('does not revalidate when registration fails', async () => {
    mocks.addProductImage.mockResolvedValue({ success: false, error: 'x', status: 500 });
    await addImageAction(PRODUCT, { storageKey: KEY });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
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
