import { minorToInput, parseMajorToMinor } from './money';
import { variantSchema, fieldErrors, type VariantInput } from './schema';

/** A variant as typed in the editor: everything is a string until it is validated. */
export type VariantDraft = {
  sku: string;
  price: string;
  compareAt: string;
  weight: string;
  stock: string;
};

export const EMPTY_VARIANT_DRAFT: VariantDraft = {
  sku: '',
  price: '',
  compareAt: '',
  weight: '',
  stock: '0',
};

export type DraftResult =
  | { ok: true; value: VariantInput }
  | { ok: false; errors: Record<string, string> };

const WHOLE_NUMBER = /^\d+$/;

function parseWhole(text: string): number | null {
  const trimmed = text.trim();
  if (!WHOLE_NUMBER.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : null;
}

function present(errors: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(errors).filter((entry): entry is [string, string] => Boolean(entry[1]))
  );
}

/**
 * Turns typed text into a validated variant. Money is parsed in the store currency minor units; an empty
 * optional field becomes null. Errors are keyed by draft field (sku, price, compareAt, weight, stock).
 */
export function draftToVariant(
  draft: VariantDraft,
  exponent: number,
  options?: Record<string, string>
): DraftResult {
  const priceMinor = parseMajorToMinor(draft.price, exponent);
  const compareAtPriceMinor =
    draft.compareAt.trim() === '' ? null : parseMajorToMinor(draft.compareAt, exponent);
  const weightGrams = draft.weight.trim() === '' ? null : parseWhole(draft.weight);
  const stock = parseWhole(draft.stock);

  const errors: Record<string, string | undefined> = {
    price: priceMinor === null ? 'Enter a price like 12.50' : undefined,
    compareAt:
      draft.compareAt.trim() !== '' && compareAtPriceMinor === null
        ? 'Enter a price like 15.00'
        : undefined,
    weight: draft.weight.trim() !== '' && weightGrams === null ? 'Enter whole grams' : undefined,
    stock: stock === null ? 'Enter a whole number' : undefined,
  };

  const parsed = variantSchema.safeParse({
    sku: draft.sku,
    priceMinor: priceMinor ?? 0,
    compareAtPriceMinor,
    weightGrams,
    stock: stock ?? 0,
    options,
  });
  if (!parsed.success) {
    const raw = fieldErrors(parsed.error);
    errors.sku ??= raw.sku;
    errors.price ??= raw.priceMinor;
    errors.compareAt ??= raw.compareAtPriceMinor;
    errors.weight ??= raw.weightGrams;
    errors.stock ??= raw.stock;
  }
  const found = present(errors);
  if (!parsed.success && Object.keys(found).length === 0)
    found.sku = 'Check this variant and try again';
  if (Object.keys(found).length > 0 || !parsed.success) return { ok: false, errors: found };
  return { ok: true, value: parsed.data };
}

/** The editor draft for an existing variant. */
export function variantToDraft(
  variant: {
    sku: string;
    price_minor: number;
    compare_at_price_minor: number | null;
    weight_grams: number | null;
    stock: number;
  },
  exponent: number
): VariantDraft {
  return {
    sku: variant.sku,
    price: minorToInput(variant.price_minor, exponent),
    compareAt:
      variant.compare_at_price_minor === null
        ? ''
        : minorToInput(variant.compare_at_price_minor, exponent),
    weight: variant.weight_grams === null ? '' : String(variant.weight_grams),
    stock: String(variant.stock),
  };
}

/** Stable key for an option combination, so typed rows survive when options are edited. */
export function comboKey(combo: Record<string, string>): string {
  return JSON.stringify(Object.entries(combo));
}
