// @vitest-environment node
/** KAN-249: the wrapper presigns and registers images through the store-scoped API. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import { addProductImage, presignProductImage } from '@/lib/api/products';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const STORE = 'store1';
const presigned = {
  upload_url: 'https://r2.example/stores/store1/a.png?X-Amz-Signature=s',
  method: 'PUT',
  headers: { 'Content-Type': 'image/png' },
  key: 'stores/store1/a.png',
  public_url: 'https://cdn.example/stores/store1/a.png',
  expires_at: '2026-01-01T00:05:00Z',
};
const png = { contentType: 'image/png', sizeBytes: 1234 } as const;

describe('image wrapper calls', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    cookieGet.mockReturnValue({ name: 'session', value: 'firebase-session-cookie' });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    cookieGet.mockReset();
  });

  it('presigns with the type and size and returns only what the browser needs', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: presigned }));

    const result = await presignProductImage(STORE, png);

    expect(result).toEqual({
      success: true,
      data: { uploadUrl: presigned.upload_url, headers: presigned.headers, key: presigned.key },
    });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe(`/v1/stores/${STORE}/uploads/images`);
    expect(await request.json()).toEqual({ content_type: 'image/png', size_bytes: 1234 });
    expect(request.headers.get('X-Internal-Key')).toBe('server-key');
  });

  it('refuses a presign body of the wrong shape', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { key: 'stores/store1/a.png' } }));
    expect(await presignProductImage(STORE, png)).toMatchObject({ success: false, status: 502 });
  });

  it('passes a backend rejection through with its status', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Unsupported image type' }, 422)
    );
    expect(await presignProductImage(STORE, png)).toMatchObject({ success: false, status: 422 });
  });

  it('registers an image on the product', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'p1' } }, 201));

    const result = await addProductImage(STORE, 'p1', {
      storage_key: 'stores/store1/a.png',
      alt_text: 'Front',
    });

    expect(result).toEqual({ success: true, data: { id: 'p1' } });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe(`/v1/stores/${STORE}/products/p1/images`);
    expect(await request.json()).toEqual({ storage_key: 'stores/store1/a.png', alt_text: 'Front' });
  });
});
