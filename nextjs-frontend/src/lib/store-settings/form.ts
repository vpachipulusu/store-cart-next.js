import { z } from 'zod';
import { MAX_MINOR, parseMajorToMinor } from '@/lib/products/money';

/**
 * Shipping and tax settings (KAN-82, KAN-83). Pure and safe for client code.
 *
 * The API keeps money as integer minor units and the tax rate in basis points (2000 = 20%). The form shows
 * major units and a percentage; parsing is string-based so no float rounding can change a value.
 */

/** Largest amount and rate the API accepts. */
export const MAX_AMOUNT_MINOR = 100_000_000_000;
export const MAX_TAX_RATE_BPS = 10_000;

/** "20" or "7.5" or "7.25" becomes 2000, 750, 725. Null for anything that is not a plain percentage. */
export function parsePercentToBps(text: string): number | null {
  const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(text.trim());
  if (!match) return null;
  const bps = Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'));
  return bps <= MAX_TAX_RATE_BPS ? bps : null;
}

/** 2000 becomes "20", 725 becomes "7.25": the value an input shows. */
export function bpsToPercentInput(bps: number): string {
  const whole = Math.floor(bps / 100);
  const fraction = String(bps % 100)
    .padStart(2, '0')
    .replace(/0+$/, '');
  return fraction === '' ? String(whole) : `${whole}.${fraction}`;
}

/** The request body the server action takes. */
export const storeSettingsSchema = z.object({
  shippingFlatRateMinor: z.number().int().min(0).max(MAX_AMOUNT_MINOR),
  freeShippingThresholdMinor: z.number().int().min(1).max(MAX_AMOUNT_MINOR).nullable(),
  taxRateBps: z.number().int().min(0).max(MAX_TAX_RATE_BPS),
  pricesIncludeTax: z.boolean(),
});

export type StoreSettingsInput = z.infer<typeof storeSettingsSchema>;

export type StoreSettingsDraft = {
  shippingFlatRate: string;
  freeShippingThreshold: string;
  taxRatePercent: string;
  pricesIncludeTax: boolean;
};

export type DraftResult =
  | { ok: true; value: StoreSettingsInput }
  | { ok: false; errors: Record<string, string> };

const AMOUNT_LIMIT = Math.min(MAX_AMOUNT_MINOR, MAX_MINOR);

/** Turns what the merchant typed into the API values, or one message per bad field. */
export function parseDraft(draft: StoreSettingsDraft, exponent: number): DraftResult {
  const errors: Record<string, string> = {};

  const flat = parseMajorToMinor(draft.shippingFlatRate, exponent);
  if (flat === null || flat > AMOUNT_LIMIT) {
    errors.shippingFlatRate = 'Enter an amount like 4.99, or 0 for free shipping.';
  }

  let threshold: number | null = null;
  if (draft.freeShippingThreshold.trim() !== '') {
    threshold = parseMajorToMinor(draft.freeShippingThreshold, exponent);
    if (threshold === null || threshold < 1 || threshold > AMOUNT_LIMIT) {
      errors.freeShippingThreshold =
        'Enter an amount above 0, or leave it empty for no free shipping.';
    }
  }

  const rate = parsePercentToBps(draft.taxRatePercent);
  if (rate === null) {
    errors.taxRatePercent = 'Enter a percentage from 0 to 100, with at most two decimals.';
  }

  if (Object.keys(errors).length > 0 || flat === null || rate === null) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    value: {
      shippingFlatRateMinor: flat,
      freeShippingThresholdMinor: threshold,
      taxRateBps: rate,
      pricesIncludeTax: draft.pricesIncludeTax,
    },
  };
}
