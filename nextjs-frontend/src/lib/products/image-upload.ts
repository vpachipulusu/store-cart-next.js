import { z } from 'zod';

/**
 * Product image upload rules (KAN-249). Pure, so the editor (before any request) and the server actions (before
 * any presign) share one definition. Limits mirror the backend (media_uploads.py: JPEG, PNG and WebP, 10 MiB,
 * no SVG); the backend stays the authority and R2 rejects a body that differs from the presigned type or size.
 */
export const IMAGE_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const;
export type ImageContentType = (typeof IMAGE_CONTENT_TYPES)[number];

export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const ALT_TEXT_MAX_LENGTH = 500;
export const IMAGE_ACCEPT = IMAGE_CONTENT_TYPES.join(',');

export const WRONG_TYPE_MESSAGE = 'Choose a JPEG, PNG or WebP image.';
export const TOO_LARGE_MESSAGE = 'That image is larger than 10 MB. Choose a smaller one.';
export const EMPTY_FILE_MESSAGE = 'That file is empty. Choose another image.';

const CONTROL_CHARACTERS = /[\p{Cc}\p{Bidi_Control}]/u;

export function isImageContentType(value: unknown): value is ImageContentType {
  return typeof value === 'string' && (IMAGE_CONTENT_TYPES as readonly string[]).includes(value);
}

/** The message for a file that must not be uploaded, or null when its type and size are allowed. */
export function imageFileError(file: { type: string; size: number }): string | null {
  if (!isImageContentType(file.type)) return WRONG_TYPE_MESSAGE;
  if (file.size <= 0) return EMPTY_FILE_MESSAGE;
  if (file.size > MAX_IMAGE_BYTES) return TOO_LARGE_MESSAGE;
  return null;
}

export const presignRequestSchema = z.object({
  contentType: z.enum(IMAGE_CONTENT_TYPES, { errorMap: () => ({ message: WRONG_TYPE_MESSAGE }) }),
  sizeBytes: z
    .number({ invalid_type_error: EMPTY_FILE_MESSAGE, required_error: EMPTY_FILE_MESSAGE })
    .int(EMPTY_FILE_MESSAGE)
    .min(1, EMPTY_FILE_MESSAGE)
    .max(MAX_IMAGE_BYTES, TOO_LARGE_MESSAGE),
});
export type PresignRequest = z.infer<typeof presignRequestSchema>;

/** Empty alt text means "none" (null); anything else is trimmed and must stay printable. */
export const altTextSchema = z.preprocess(
  (value) => value ?? '',
  z
    .string()
    .trim()
    .max(ALT_TEXT_MAX_LENGTH, `Alt text must be ${ALT_TEXT_MAX_LENGTH} characters or fewer`)
    .refine((value) => !CONTROL_CHARACTERS.test(value), 'Alt text contains invalid characters')
    .transform((value) => (value === '' ? null : value))
);

const KEY_MAX_LENGTH = 255;
const KEY_FILE_PATTERN = /^[A-Za-z0-9_-]+\.(jpg|png|webp)$/;

/** One path segment under the store's own prefix with an allowed extension, like the backend's check. */
export function isStoreImageKey(storeId: string, key: unknown): key is string {
  if (typeof key !== 'string' || key.length > KEY_MAX_LENGTH) return false;
  const prefix = `stores/${storeId}/`;
  return key.startsWith(prefix) && KEY_FILE_PATTERN.test(key.slice(prefix.length));
}
