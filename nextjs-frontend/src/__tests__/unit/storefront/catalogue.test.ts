/** KAN-75: pure storefront catalogue helpers (paging, search text, money, categories, variants). */
import { describe, expect, it } from 'vitest';
import {
  categoryTrail,
  childCategories,
  cleanSearch,
  findVariant,
  formatMoney,
  formatPriceRange,
  initialSelection,
  MAX_PAGE,
  pageCount,
  parsePage,
  summarise,
  type ProductVariant,
  type StoreCategory,
} from '@/lib/storefront/catalogue';

const variant = (id: string, values: string[], inStock = true): ProductVariant => ({
  id,
  priceMinor: 1000,
  compareAtPriceMinor: null,
  inStock,
  optionValueIds: values,
});

const categories: StoreCategory[] = [
  { name: 'Clothing', slug: 'clothing', parentSlug: null },
  { name: 'Home', slug: 'home', parentSlug: null },
  { name: 'Tops', slug: 'tops', parentSlug: 'clothing' },
  { name: 'Tees', slug: 'tees', parentSlug: 'tops' },
];

describe('parsePage', () => {
  it.each([
    [undefined, 1],
    ['1', 1],
    ['3', 3],
    [['4', '9'], 4],
    ['0', 1],
    ['-2', 1],
    ['02', 1],
    ['2.5', 1],
    ['abc', 1],
    ['9999999', 1],
    [String(MAX_PAGE + 5), MAX_PAGE],
  ])('%s is page %s', (raw, expected) => {
    expect(parsePage(raw as string | string[] | undefined)).toBe(expected);
  });
});

describe('cleanSearch', () => {
  it('trims, collapses whitespace and caps the length', () => {
    expect(cleanSearch('  blue   mug ')).toBe('blue mug');
    expect(cleanSearch(['tee', 'other'])).toBe('tee');
    expect(cleanSearch(undefined)).toBe('');
    expect(cleanSearch('x'.repeat(150))).toHaveLength(100);
  });
});

describe('pageCount', () => {
  it('is at least 1 and at most MAX_PAGE', () => {
    expect(pageCount(0)).toBe(1);
    expect(pageCount(24)).toBe(1);
    expect(pageCount(25)).toBe(2);
    expect(pageCount(10_000_000)).toBe(MAX_PAGE);
  });
});

describe('money', () => {
  it('formats minor units by the currency exponent', () => {
    expect(formatMoney(1250, 'GBP')).toBe('£12.50');
    expect(formatMoney(1250, 'JPY')).toBe('JP¥1,250');
  });

  it('shows the code when the currency is not valid', () => {
    expect(formatMoney(1250, 'NOPE!')).toBe('12.50 NOPE!');
  });

  it('shows a range as "From" the lowest price', () => {
    expect(formatPriceRange(1000, 1500, 'GBP')).toBe('From £10.00');
    expect(formatPriceRange(1000, 1000, 'GBP')).toBe('£10.00');
    expect(formatPriceRange(null, null, 'GBP')).toBeNull();
  });
});

describe('categories', () => {
  it('lists the children of a parent, roots for null', () => {
    expect(childCategories(categories, null).map((c) => c.slug)).toEqual(['clothing', 'home']);
    expect(childCategories(categories, 'clothing').map((c) => c.slug)).toEqual(['tops']);
  });

  it('builds the trail root first', () => {
    expect(categoryTrail(categories, 'tees').map((c) => c.slug)).toEqual([
      'clothing',
      'tops',
      'tees',
    ]);
    expect(categoryTrail(categories, 'missing')).toEqual([]);
  });

  it('stops on a cycle', () => {
    const looped: StoreCategory[] = [
      { name: 'A', slug: 'a', parentSlug: 'b' },
      { name: 'B', slug: 'b', parentSlug: 'a' },
    ];
    expect(categoryTrail(looped, 'a').map((c) => c.slug)).toEqual(['b', 'a']);
  });
});

describe('variants', () => {
  const variants = [variant('s', ['size-s', 'red'], false), variant('m', ['size-m', 'red'])];

  it('finds the variant for a selection in any order', () => {
    expect(findVariant(variants, ['red', 'size-m'])?.id).toBe('m');
    expect(findVariant(variants, ['size-l', 'red'])).toBeNull();
  });

  it('starts on the first variant in stock', () => {
    expect(initialSelection(variants)).toEqual(['size-m', 'red']);
    expect(initialSelection([variant('only', ['x'], false)])).toEqual(['x']);
    expect(initialSelection([])).toEqual([]);
  });

  it('matches a product without options', () => {
    expect(findVariant([variant('one', [])], [])?.id).toBe('one');
  });
});

describe('summarise', () => {
  it('collapses whitespace and cuts at a word', () => {
    expect(summarise('  Soft\n\ncotton  tee ')).toBe('Soft cotton tee');
    expect(summarise('', 10)).toBeUndefined();
    expect(summarise(null)).toBeUndefined();
    expect(summarise('one two three four five', 12)).toBe('one two…');
  });
});
