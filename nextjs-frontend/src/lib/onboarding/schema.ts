import { z } from 'zod';

/**
 * Merchant onboarding input (KAN-60). Pure, so the form and the server action share one definition.
 * Limits mirror the backend (app/core/slugs.py: 3 to 63 characters, lowercase letters, digits and single hyphens;
 * names 1 to 100 characters); the backend stays the authority and answers 422 for anything stricter, such as
 * reserved slugs.
 */
export const NAME_MAX_LENGTH = 100;
export const SLUG_MIN_LENGTH = 3;
export const SLUG_MAX_LENGTH = 63;

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// Control characters (C0, DEL, C1) and bidi overrides are rejected by the backend too.
const FORBIDDEN_NAME_CHARACTERS = /[\p{Cc}\p{Bidi_Control}]/u;

const nameField = (label: string) =>
  z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .max(NAME_MAX_LENGTH, `${label} must be ${NAME_MAX_LENGTH} characters or fewer`)
    .refine(
      (value) => !FORBIDDEN_NAME_CHARACTERS.test(value),
      `${label} contains invalid characters`
    );

const slugField = (label: string) =>
  z
    .string()
    .trim()
    .min(SLUG_MIN_LENGTH, `${label} must be at least ${SLUG_MIN_LENGTH} characters`)
    .max(SLUG_MAX_LENGTH, `${label} must be ${SLUG_MAX_LENGTH} characters or fewer`)
    .regex(SLUG_PATTERN, `${label} can use lowercase letters, numbers and single hyphens only`);

export const onboardingSchema = z.object({
  organizationName: nameField('Business name'),
  organizationSlug: slugField('Business address'),
  storeName: nameField('Store name'),
  storeSlug: slugField('Store address'),
});

export type OnboardingInput = z.infer<typeof onboardingSchema>;

/** Resume mode: the business already exists, so only the store is submitted. */
export const resumeSchema = onboardingSchema.pick({ storeName: true, storeSlug: true });
export type ResumeInput = z.infer<typeof resumeSchema>;

export type OnboardingSubmission =
  | ({ mode: 'new' } & OnboardingInput)
  | ({ mode: 'resume' } & ResumeInput);

export type FieldName = keyof OnboardingInput;
export type FieldErrors = Partial<Record<FieldName, string>>;

const FIELD_NAMES: ReadonlySet<string> = new Set<FieldName>([
  'organizationName',
  'organizationSlug',
  'storeName',
  'storeSlug',
]);

export function isFieldName(value: unknown): value is FieldName {
  return typeof value === 'string' && FIELD_NAMES.has(value);
}

export const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Please sign in again.';

/** Suggests a slug from a display name; the user can edit it. */
export function slugify(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, SLUG_MAX_LENGTH)
    .replace(/-+$/g, '');
}
