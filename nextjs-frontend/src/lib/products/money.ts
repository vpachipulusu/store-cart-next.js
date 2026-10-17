/**
 * Money for the product screens (KAN-73). Pure and safe for client code.
 *
 * The API stores prices as integer minor units in the store currency (backend-products-api.md); the editor shows
 * and accepts major units. Parsing is string-based so no float rounding can change a price.
 */

/** Largest price the API accepts (2^53 - 1, JavaScript safe). */
export const MAX_MINOR = Number.MAX_SAFE_INTEGER;

/** Decimal places of a currency (JPY 0, USD 2, KWD 3). Unknown codes fall back to 2. */
export function currencyExponent(currency: string): number {
  try {
    const digits = new Intl.NumberFormat('en', {
      style: 'currency',
      currency,
    }).resolvedOptions().maximumFractionDigits;
    return digits ?? 2;
  } catch {
    return 2;
  }
}

/** "12.5" with exponent 2 becomes 1250. Returns null for anything that is not a plain non-negative amount. */
export function parseMajorToMinor(text: string, exponent: number): number | null {
  const trimmed = text.trim();
  const match = /^(\d+)(?:\.(\d*))?$/.exec(trimmed);
  if (!match) return null;
  const fraction = match[2] ?? '';
  if (fraction.length > exponent) return null;
  const minor = Number(match[1] + fraction.padEnd(exponent, '0'));
  return Number.isSafeInteger(minor) ? minor : null;
}

/** 1250 with exponent 2 becomes "12.50": the value an input shows. */
export function minorToInput(minor: number, exponent: number): string {
  if (exponent === 0) return String(minor);
  const digits = String(minor).padStart(exponent + 1, '0');
  return `${digits.slice(0, -exponent)}.${digits.slice(-exponent)}`;
}

/** 1250 and "GBP" become "£12.50". */
export function formatMinor(minor: number, currency: string): string {
  try {
    // A decimal string keeps the cents exact for amounts beyond what a float holds.
    return new Intl.NumberFormat('en', { style: 'currency', currency }).format(
      minorToInput(minor, currencyExponent(currency)) as unknown as number
    );
  } catch {
    return `${minorToInput(minor, 2)} ${currency}`;
  }
}

/** One price or a "low – high" range for a product's variants. */
export function formatPriceRange(
  min: number | null,
  max: number | null,
  currency: string
): string | null {
  if (min === null || max === null) return null;
  return min === max
    ? formatMinor(min, currency)
    : `${formatMinor(min, currency)} – ${formatMinor(max, currency)}`;
}
