/**
 * One locale for every number and amount on the admin analytics pages. en-US so USD reads as a dollar sign,
 * GBP as a pound sign and EUR as a euro sign (en-GB would write US$).
 */
export const ADMIN_NUMBER_LOCALE = 'en-US';

export function formatCount(value: number): string {
  return value.toLocaleString(ADMIN_NUMBER_LOCALE);
}

/** Formats an amount in minor units (cents) using the currency's own number of decimals (JPY has none). */
export function formatMinorUnits(amountMinor: number, currency: string): string {
  try {
    const format = new Intl.NumberFormat(ADMIN_NUMBER_LOCALE, { style: 'currency', currency });
    const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(amountMinor / 10 ** digits);
  } catch {
    return `${amountMinor} ${currency}`;
  }
}
