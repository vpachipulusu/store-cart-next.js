import { z } from 'zod';
import { MAX_MINOR } from './money';

/**
 * Product editor input (KAN-73). Pure, so the forms and the server actions share one definition. Limits mirror
 * the backend (backend-products-api.md); the backend stays the authority and answers 422 for anything stricter.
 */
export const TITLE_MAX_LENGTH = 255;
export const SLUG_MAX_LENGTH = 200;
export const SKU_MAX_LENGTH = 100;
export const MAX_OPTIONS = 3;
export const MAX_OPTION_VALUES = 50;
export const MAX_VARIANTS = 100;
export const MAX_CATEGORIES = 50;
export const MAX_COUNT = 1_000_000_000;

export const PRODUCT_STATUSES = ['draft', 'active'] as const;
export type ProductStatus = (typeof PRODUCT_STATUSES)[number];

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const CONTROL_CHARACTERS = /[\p{Cc}\p{Bidi_Control}]/u;
/** Ids are opaque strings; this only screens out junk before the backend (which owns the real check). */
export const ENTITY_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function isEntityId(value: unknown): value is string {
  return typeof value === 'string' && ENTITY_ID_PATTERN.test(value);
}

const entityId = z.string().regex(ENTITY_ID_PATTERN, 'Enter a valid id');

/** Empty text or null (an already parsed value sent back) both mean "not set". */
const optionalText = (max: number, label: string) =>
  z.preprocess(
    (value) => value ?? '',
    z
      .string()
      .trim()
      .max(max, `${label} must be ${max} characters or fewer`)
      .transform((value) => (value === '' ? null : value))
  );

export const variantSchema = z
  .object({
    sku: z
      .string()
      .trim()
      .min(1, 'SKU is required')
      .max(SKU_MAX_LENGTH, `SKU must be ${SKU_MAX_LENGTH} characters or fewer`)
      .refine((value) => !CONTROL_CHARACTERS.test(value), 'SKU contains invalid characters'),
    priceMinor: z.number().int('Enter a valid price').min(0, 'Enter a valid price').max(MAX_MINOR),
    compareAtPriceMinor: z.number().int().min(0).max(MAX_MINOR).nullable(),
    weightGrams: z.number().int().min(0).max(MAX_COUNT).nullable(),
    stock: z.number().int('Stock must be a whole number').min(0).max(MAX_COUNT),
    options: z.record(z.string().trim().min(1), z.string().trim().min(1)).optional(),
  })
  .refine(
    (variant) =>
      variant.compareAtPriceMinor === null || variant.compareAtPriceMinor >= variant.priceMinor,
    { path: ['compareAtPriceMinor'], message: 'Compare-at price must not be below the price' }
  );
export type VariantInput = z.infer<typeof variantSchema>;

export const optionSchema = z.object({
  name: z.string().trim().min(1, 'Option name is required').max(100),
  values: z
    .array(z.string().trim().min(1).max(100))
    .min(1, 'Add at least one value')
    .max(MAX_OPTION_VALUES, `At most ${MAX_OPTION_VALUES} values per option`),
});
export type OptionInput = z.infer<typeof optionSchema>;

const detailsShape = {
  title: z
    .string()
    .trim()
    .min(1, 'Title is required')
    .max(TITLE_MAX_LENGTH, `Title must be ${TITLE_MAX_LENGTH} characters or fewer`),
  slug: optionalText(SLUG_MAX_LENGTH, 'Slug').refine(
    (value) => value === null || SLUG_PATTERN.test(value),
    'Slug may use lowercase letters, digits and single hyphens'
  ),
  description: optionalText(20_000, 'Description'),
  status: z.enum(PRODUCT_STATUSES),
  categoryIds: z.array(entityId).max(MAX_CATEGORIES, `At most ${MAX_CATEGORIES} categories`),
};

export const productDetailsSchema = z.object(detailsShape);
export type ProductDetailsInput = z.infer<typeof productDetailsSchema>;

export const createProductSchema = z
  .object({
    ...detailsShape,
    options: z.array(optionSchema).max(MAX_OPTIONS, `At most ${MAX_OPTIONS} options`),
    variants: z
      .array(variantSchema)
      .min(1, 'A product needs at least one variant')
      .max(MAX_VARIANTS, `At most ${MAX_VARIANTS} variants`),
  })
  .refine(
    (product) =>
      new Set(product.variants.map((variant) => variant.sku.toLowerCase())).size ===
      product.variants.length,
    { path: ['variants'], message: 'Each variant needs its own SKU' }
  )
  .refine(
    (product) =>
      new Set(product.options.map((option) => option.name.toLowerCase())).size ===
      product.options.length,
    { path: ['options'], message: 'Each option needs a different name' }
  );
export type CreateProductInput = z.infer<typeof createProductSchema>;

/** First message per top-level field, for showing next to inputs. */
export function fieldErrors(error: z.ZodError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? 'form');
    if (!out[key]) out[key] = issue.message;
  }
  return out;
}

/** Cartesian product of option values: [{Size:'S',Color:'Red'}, ...]. No options gives one empty combination. */
export function optionCombinations(
  options: ReadonlyArray<OptionInput>
): ReadonlyArray<Record<string, string>> {
  return options.reduce<ReadonlyArray<Record<string, string>>>(
    (combos, option) =>
      combos.flatMap((combo) => option.values.map((value) => ({ ...combo, [option.name]: value }))),
    [{}]
  );
}

/**
 * Like optionCombinations, but each combination carries a key made of the positions of its values, not their
 * text, so a row keeps what was typed when an option is renamed or a value is added after it.
 */
export function indexedCombinations(
  options: ReadonlyArray<OptionInput>
): ReadonlyArray<{ key: string; values: Record<string, string> }> {
  return options.reduce<ReadonlyArray<{ key: string; values: Record<string, string> }>>(
    (combos, option) =>
      combos.flatMap((combo) =>
        option.values.map((value, index) => ({
          key: combo.key === '' ? String(index) : `${combo.key}.${index}`,
          values: { ...combo.values, [option.name]: value },
        }))
      ),
    [{ key: '', values: {} }]
  );
}
