import { describe, expect, it } from 'vitest';
import { comboKey, draftToVariant, variantToDraft } from '@/lib/products/draft';

const draft = { sku: 'TEE-1', price: '12.50', compareAt: '', weight: '', stock: '4' };

describe('draftToVariant', () => {
  it('converts money to minor units and empty optionals to null', () => {
    expect(draftToVariant(draft, 2)).toEqual({
      ok: true,
      value: {
        sku: 'TEE-1',
        priceMinor: 1250,
        compareAtPriceMinor: null,
        weightGrams: null,
        stock: 4,
        options: undefined,
      },
    });
  });

  it('keeps chosen options and optional numbers', () => {
    const result = draftToVariant({ ...draft, compareAt: '15', weight: '250' }, 2, { Size: 'M' });
    expect(result).toMatchObject({
      ok: true,
      value: { compareAtPriceMinor: 1500, weightGrams: 250, options: { Size: 'M' } },
    });
  });

  it('reports every bad field at once', () => {
    const result = draftToVariant(
      { sku: '', price: 'abc', compareAt: 'x', weight: '1.5', stock: '-2' },
      2
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(Object.keys(result.errors).sort()).toEqual([
        'compareAt',
        'price',
        'sku',
        'stock',
        'weight',
      ]);
    }
  });

  it('flags a compare-at price below the price on the compare-at field', () => {
    const result = draftToVariant({ ...draft, compareAt: '5' }, 2);
    expect(result).toEqual({
      ok: false,
      errors: { compareAt: 'Compare-at price must not be below the price' },
    });
  });

  it('rejects decimals for a zero-decimal currency', () => {
    expect(draftToVariant({ ...draft, price: '10.5' }, 0).ok).toBe(false);
  });
});

describe('variantToDraft', () => {
  it('shows money in major units and nulls as empty text', () => {
    expect(
      variantToDraft(
        { sku: 'A', price_minor: 1999, compare_at_price_minor: null, weight_grams: null, stock: 0 },
        2
      )
    ).toEqual({ sku: 'A', price: '19.99', compareAt: '', weight: '', stock: '0' });
  });

  it('shows compare-at and weight when set', () => {
    const result = variantToDraft(
      { sku: 'A', price_minor: 1000, compare_at_price_minor: 1500, weight_grams: 90, stock: 2 },
      2
    );
    expect(result).toMatchObject({ compareAt: '15.00', weight: '90' });
  });
});

describe('comboKey', () => {
  it('is stable for equal combinations and differs otherwise', () => {
    expect(comboKey({ Size: 'S' })).toBe(comboKey({ Size: 'S' }));
    expect(comboKey({ Size: 'S' })).not.toBe(comboKey({ Size: 'M' }));
  });
});
