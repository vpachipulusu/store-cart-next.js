/** KAN-82, KAN-83: the shipping and tax form turns typed text into exact minor units and basis points. */
import { describe, expect, it } from 'vitest';
import {
  bpsToPercentInput,
  isKnownCurrency,
  normaliseDecimal,
  parseDraft,
  parsePercentToBps,
  storeSettingsSchema,
  type StoreSettingsDraft,
} from '@/lib/store-settings/form';

const draft = (over: Partial<StoreSettingsDraft> = {}): StoreSettingsDraft => ({
  shippingFlatRate: '4.99',
  freeShippingThreshold: '50',
  taxRatePercent: '20',
  pricesIncludeTax: false,
  ...over,
});

describe('parsePercentToBps', () => {
  it.each([
    ['20', 2000],
    ['7.5', 750],
    ['7.25', 725],
    ['0', 0],
    ['100', 10000],
    [' 5 ', 500],
  ])('%s -> %i', (text, bps) => {
    expect(parsePercentToBps(text)).toBe(bps);
  });

  it.each(['', '-1', '100.01', '101', '7.255', 'abc', '1e2', '5%'])('rejects %j', (text) => {
    expect(parsePercentToBps(text)).toBeNull();
  });
});

describe('bpsToPercentInput', () => {
  it.each([
    [2000, '20'],
    [750, '7.5'],
    [725, '7.25'],
    [0, '0'],
    [5, '0.05'],
  ])('%i -> %s', (bps, text) => {
    expect(bpsToPercentInput(bps)).toBe(text);
  });
});

describe('parseDraft', () => {
  it('converts amounts to minor units and the rate to basis points', () => {
    expect(parseDraft(draft({ pricesIncludeTax: true }), 2)).toEqual({
      ok: true,
      value: {
        shippingFlatRateMinor: 499,
        freeShippingThresholdMinor: 5000,
        taxRateBps: 2000,
        pricesIncludeTax: true,
      },
    });
  });

  it('treats an empty threshold as no free shipping', () => {
    const result = parseDraft(draft({ freeShippingThreshold: '  ' }), 2);
    expect(result.ok && result.value.freeShippingThresholdMinor).toBeNull();
  });

  it('respects the currency exponent', () => {
    const result = parseDraft(draft({ shippingFlatRate: '500', freeShippingThreshold: '' }), 0);
    expect(result.ok && result.value.shippingFlatRateMinor).toBe(500);
  });

  it('reports one message per bad field', () => {
    const result = parseDraft(
      draft({ shippingFlatRate: '-1', freeShippingThreshold: '0', taxRatePercent: '120' }),
      2
    );
    expect(result).toEqual({
      ok: false,
      errors: {
        shippingFlatRate: expect.any(String),
        freeShippingThreshold: expect.any(String),
        taxRatePercent: expect.any(String),
      },
    });
  });

  it('rejects more decimals than the currency has', () => {
    expect(parseDraft(draft({ shippingFlatRate: '4.999' }), 2).ok).toBe(false);
  });
});

describe('storeSettingsSchema', () => {
  const valid = {
    storeId: 'store1',
    shippingFlatRateMinor: 0,
    freeShippingThresholdMinor: null,
    taxRateBps: 10000,
    pricesIncludeTax: false,
  };

  it('accepts the edges', () => {
    expect(storeSettingsSchema.safeParse(valid).success).toBe(true);
  });

  it.each([
    { shippingFlatRateMinor: -1 },
    { freeShippingThresholdMinor: 0 },
    { taxRateBps: 10001 },
    { taxRateBps: 1.5 },
    { storeId: '' },
  ])('rejects %j', (over) => {
    expect(storeSettingsSchema.safeParse({ ...valid, ...over }).success).toBe(false);
  });
});

describe('normaliseDecimal', () => {
  it.each([
    ['7,5', '7.5'],
    [' 4,99 ', '4.99'],
    ['7.5', '7.5'],
    ['1,234,5', '1,234,5'],
    ['1.234,5', '1.234,5'],
  ])('%s -> %s', (text, expected) => {
    expect(normaliseDecimal(text)).toBe(expected);
  });

  it('lets parseDraft read comma decimals', () => {
    const result = parseDraft(
      draft({ shippingFlatRate: '4,99', freeShippingThreshold: '50,5', taxRatePercent: '7,25' }),
      2
    );
    expect(result).toMatchObject({
      ok: true,
      value: { shippingFlatRateMinor: 499, freeShippingThresholdMinor: 5050, taxRateBps: 725 },
    });
  });
});

describe('isKnownCurrency', () => {
  it.each(['GBP', 'JPY', 'KWD'])('knows %s', (code) => expect(isKnownCurrency(code)).toBe(true));
  it.each(['', 'gbp', 'ZZZZ', 'G1P', 'XX'])('rejects %j', (code) =>
    expect(isKnownCurrency(code)).toBe(false)
  );
});
