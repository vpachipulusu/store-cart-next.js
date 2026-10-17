// en-US so USD reads as a dollar sign, GBP as a pound sign and EUR as a euro sign (en-GB writes US$).
const LOCALE = 'en-US';

/** Formats an amount in minor units (cents) using the currency's own number of decimals (JPY has none). */
export function formatMinorUnits(amountMinor: number, currency: string): string {
  try {
    const format = new Intl.NumberFormat(LOCALE, { style: 'currency', currency });
    const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(amountMinor / 10 ** digits);
  } catch {
    return `${amountMinor} ${currency}`;
  }
}
