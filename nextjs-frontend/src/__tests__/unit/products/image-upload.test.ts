/** KAN-249: shared image upload rules (type, size, alt text, store key prefix). */
import { describe, expect, it } from 'vitest';
import {
  ALT_TEXT_MAX_LENGTH,
  altTextSchema,
  EMPTY_FILE_MESSAGE,
  imageFileError,
  isStoreImageKey,
  MAX_IMAGE_BYTES,
  presignRequestSchema,
  TOO_LARGE_MESSAGE,
  WRONG_TYPE_MESSAGE,
} from '@/lib/products/image-upload';

describe('imageFileError', () => {
  it.each(['image/jpeg', 'image/png', 'image/webp'])('allows %s', (type) => {
    expect(imageFileError({ type, size: 1000 })).toBeNull();
  });

  it.each(['image/svg+xml', 'image/gif', 'application/pdf', ''])('rejects type "%s"', (type) => {
    expect(imageFileError({ type, size: 1000 })).toBe(WRONG_TYPE_MESSAGE);
  });

  it('allows exactly the maximum size and rejects one byte over', () => {
    expect(imageFileError({ type: 'image/png', size: MAX_IMAGE_BYTES })).toBeNull();
    expect(imageFileError({ type: 'image/png', size: MAX_IMAGE_BYTES + 1 })).toBe(
      TOO_LARGE_MESSAGE
    );
  });

  it('rejects an empty file', () => {
    expect(imageFileError({ type: 'image/png', size: 0 })).toBe(EMPTY_FILE_MESSAGE);
  });
});

describe('presignRequestSchema', () => {
  it('accepts an allowed type and size', () => {
    const parsed = presignRequestSchema.safeParse({ contentType: 'image/webp', sizeBytes: 5 });
    expect(parsed.success).toBe(true);
  });

  it.each([
    [{ contentType: 'image/svg+xml', sizeBytes: 5 }, WRONG_TYPE_MESSAGE],
    [{ contentType: 'image/png', sizeBytes: MAX_IMAGE_BYTES + 1 }, TOO_LARGE_MESSAGE],
    [{ contentType: 'image/png', sizeBytes: 1.5 }, EMPTY_FILE_MESSAGE],
    [{ contentType: 'image/png', sizeBytes: 'big' }, EMPTY_FILE_MESSAGE],
    [{ contentType: 'image/png' }, EMPTY_FILE_MESSAGE],
    [{ contentType: 'image/png', sizeBytes: 0 }, EMPTY_FILE_MESSAGE],
  ])('rejects %j', (input, message) => {
    const parsed = presignRequestSchema.safeParse(input);
    expect(parsed.success).toBe(false);
    if (!parsed.success) expect(parsed.error.issues[0].message).toBe(message);
  });
});

describe('altTextSchema', () => {
  it('turns blank, null and undefined into null and trims text', () => {
    expect(altTextSchema.parse('  ')).toBeNull();
    expect(altTextSchema.parse(null)).toBeNull();
    expect(altTextSchema.parse(undefined)).toBeNull();
    expect(altTextSchema.parse('  Front view ')).toBe('Front view');
  });

  it('rejects text over the limit and control characters', () => {
    expect(altTextSchema.safeParse('a'.repeat(ALT_TEXT_MAX_LENGTH + 1)).success).toBe(false);
    expect(altTextSchema.safeParse('bad\u0007text').success).toBe(false);
  });
});

describe('isStoreImageKey', () => {
  it('accepts one segment under the store prefix with an allowed extension', () => {
    expect(isStoreImageKey('s1', 'stores/s1/abc_DEF-1.jpg')).toBe(true);
    expect(isStoreImageKey('s1', 'stores/s1/abc.webp')).toBe(true);
  });

  it.each([
    'stores/s2/abc.jpg',
    'stores/s1/nested/abc.jpg',
    'stores/s1/abc.svg',
    'stores/s1/abc.jpg.exe',
    'stores/s1/../s2/abc.jpg',
    '/stores/s1/abc.jpg',
    `stores/s1/${'a'.repeat(300)}.jpg`,
    42,
    null,
  ])('rejects %s', (key) => {
    expect(isStoreImageKey('s1', key)).toBe(false);
  });
});
