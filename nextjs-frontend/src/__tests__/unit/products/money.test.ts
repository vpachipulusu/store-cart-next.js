import { describe, expect, it } from 'vitest';
import {
  currencyExponent,
  formatMinor,
  formatPriceRange,
  minorToInput,
  parseMajorToMinor,
} from '@/lib/products/money';

describe('currencyExponent', () => {
  it.each([
    ['USD', 2],
    ['JPY', 0],
    ['KWD', 3],
  ])('%s has %i decimals', (code, digits) => {
    expect(currencyExponent(code)).toBe(digits);
  });

  it('falls back to 2 for a code Intl rejects', () => {
    expect(currencyExponent('not-a-code')).toBe(2);
  });
});

describe('parseMajorToMinor', () => {
  it.each([
    ['12.50', 2, 1250],
    ['12.5', 2, 1250],
    ['12', 2, 1200],
    ['0.05', 2, 5],
    ['1200', 0, 1200],
    ['1.234', 3, 1234],
    [' 7 ', 2, 700],
    ['12.', 2, 1200],
  ])('%s with exponent %i is %i', (text, exponent, expected) => {
    expect(parseMajorToMinor(text, exponent)).toBe(expected);
  });

  it.each(['', 'abc', '-1', '1.234', '1,50', '1e3', '.5'])('rejects %j', (text) => {
    expect(parseMajorToMinor(text, 2)).toBeNull();
  });

  it('rejects decimals when the currency has none', () => {
    expect(parseMajorToMinor('10.5', 0)).toBeNull();
  });

  it('rejects an amount beyond the safe integer range', () => {
    expect(parseMajorToMinor('99999999999999999999', 2)).toBeNull();
  });

  it('does not lose cents to float rounding', () => {
    expect(parseMajorToMinor('19.99', 2)).toBe(1999);
    expect(parseMajorToMinor('0.29', 2)).toBe(29);
  });
});

describe('minorToInput', () => {
  it.each([
    [1250, 2, '12.50'],
    [5, 2, '0.05'],
    [0, 2, '0.00'],
    [1200, 0, '1200'],
    [1234, 3, '1.234'],
  ])('%i with exponent %i is %s', (minor, exponent, expected) => {
    expect(minorToInput(minor, exponent)).toBe(expected);
  });

  it('round-trips with parseMajorToMinor', () => {
    expect(parseMajorToMinor(minorToInput(98765, 2), 2)).toBe(98765);
  });
});

describe('formatMinor and formatPriceRange', () => {
  it('formats in the store currency', () => {
    expect(formatMinor(1250, 'USD')).toBe('$12.50');
    expect(formatMinor(1200, 'JPY')).toContain('1,200');
  });

  it('keeps the cents exact for a large amount', () => {
    expect(formatMinor(9007199254740991, 'USD')).toContain('90,071,992,547,409.91');
  });

  it('falls back to a plain amount for an unknown currency', () => {
    expect(formatMinor(1250, 'not-a-code')).toBe('12.50 not-a-code');
  });

  it('shows one price, a range, or nothing', () => {
    expect(formatPriceRange(1000, 1000, 'USD')).toBe('$10.00');
    expect(formatPriceRange(1000, 2500, 'USD')).toBe('$10.00 – $25.00');
    expect(formatPriceRange(null, null, 'USD')).toBeNull();
  });
});
