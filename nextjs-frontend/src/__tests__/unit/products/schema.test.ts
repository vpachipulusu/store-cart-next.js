import { describe, expect, it } from 'vitest';
import {
  createProductSchema,
  fieldErrors,
  indexedCombinations,
  isEntityId,
  optionCombinations,
  productDetailsSchema,
  variantSchema,
} from '@/lib/products/schema';

const variant = {
  sku: 'TEE-1',
  priceMinor: 1000,
  compareAtPriceMinor: null,
  weightGrams: null,
  stock: 3,
};

describe('variantSchema', () => {
  it('accepts a minimal variant and trims the SKU', () => {
    expect(variantSchema.parse({ ...variant, sku: '  TEE-1  ' }).sku).toBe('TEE-1');
  });

  it('rejects a compare-at price below the price', () => {
    const result = variantSchema.safeParse({ ...variant, compareAtPriceMinor: 500 });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(fieldErrors(result.error).compareAtPriceMinor).toMatch(/below the price/);
    }
  });

  it('accepts a compare-at price equal to or above the price', () => {
    expect(variantSchema.safeParse({ ...variant, compareAtPriceMinor: 1000 }).success).toBe(true);
    expect(variantSchema.safeParse({ ...variant, compareAtPriceMinor: 1500 }).success).toBe(true);
  });

  it.each([
    ['empty SKU', { sku: '   ' }],
    ['SKU over 100 characters', { sku: 'x'.repeat(101) }],
    ['SKU with a control character', { sku: 'a\u0007b' }],
    ['fractional price', { priceMinor: 10.5 }],
    ['negative price', { priceMinor: -1 }],
    ['price beyond safe integers', { priceMinor: Number.MAX_SAFE_INTEGER + 2 }],
    ['negative stock', { stock: -1 }],
    ['stock over the limit', { stock: 1_000_000_001 }],
    ['weight over the limit', { weightGrams: 1_000_000_001 }],
  ])('rejects %s', (_name, patch) => {
    expect(variantSchema.safeParse({ ...variant, ...patch }).success).toBe(false);
  });
});

describe('productDetailsSchema', () => {
  const details = { title: 'Tee', slug: '', description: '', status: 'draft', categoryIds: [] };

  it('turns empty slug and description into null', () => {
    const parsed = productDetailsSchema.parse(details);
    expect(parsed.slug).toBeNull();
    expect(parsed.description).toBeNull();
  });

  it.each([
    ['blank title', { title: '  ' }],
    ['title over 255 characters', { title: 'x'.repeat(256) }],
    ['upper-case slug', { slug: 'Tee' }],
    ['slug with a double hyphen', { slug: 'a--b' }],
    ['unknown status', { status: 'archived' }],
    ['a category id with a slash', { categoryIds: ['a/b'] }],
    ['more than 50 categories', { categoryIds: Array.from({ length: 51 }, (_, i) => `c${i}`) }],
  ])('rejects %s', (_name, patch) => {
    expect(productDetailsSchema.safeParse({ ...details, ...patch }).success).toBe(false);
  });
});

describe('createProductSchema', () => {
  const base = {
    title: 'Tee',
    slug: '',
    description: '',
    status: 'draft',
    categoryIds: [],
    options: [],
    variants: [variant],
  };

  it('accepts a product without options and one variant', () => {
    expect(createProductSchema.safeParse(base).success).toBe(true);
  });

  it('needs at least one variant', () => {
    expect(createProductSchema.safeParse({ ...base, variants: [] }).success).toBe(false);
  });

  it('rejects two variants with the same SKU ignoring case', () => {
    const result = createProductSchema.safeParse({
      ...base,
      variants: [variant, { ...variant, sku: 'tee-1' }],
    });
    expect(result.success).toBe(false);
    if (!result.success) expect(fieldErrors(result.error).variants).toMatch(/own SKU/);
  });

  it('rejects option names that differ only by case', () => {
    const options = [
      { name: 'Size', values: ['S'] },
      { name: 'size', values: ['M'] },
    ];
    const result = createProductSchema.safeParse({ ...base, options });
    expect(result.success).toBe(false);
    if (!result.success) expect(fieldErrors(result.error).options).toMatch(/different name/);
  });

  it('rejects more than three options', () => {
    const options = ['A', 'B', 'C', 'D'].map((name) => ({ name, values: ['x'] }));
    expect(createProductSchema.safeParse({ ...base, options }).success).toBe(false);
  });
});

describe('helpers', () => {
  it('isEntityId screens out junk', () => {
    expect(isEntityId('tz4a98xxat96iws9zmbrgj3a')).toBe(true);
    expect(isEntityId('')).toBe(false);
    expect(isEntityId('a b')).toBe(false);
    expect(isEntityId('../x')).toBe(false);
    expect(isEntityId(42)).toBe(false);
  });

  it('optionCombinations builds the cartesian product, or one empty combo', () => {
    expect(optionCombinations([])).toEqual([{}]);
    expect(
      optionCombinations([
        { name: 'Size', values: ['S', 'M'] },
        { name: 'Color', values: ['Red'] },
      ])
    ).toEqual([
      { Size: 'S', Color: 'Red' },
      { Size: 'M', Color: 'Red' },
    ]);
  });
});

describe('indexedCombinations', () => {
  it('keys each combination by the positions of its values', () => {
    const combos = indexedCombinations([
      { name: 'Size', values: ['S', 'M'] },
      { name: 'Color', values: ['Red', 'Blue'] },
    ]);
    expect(combos.map((combo) => combo.key)).toEqual(['0.0', '0.1', '1.0', '1.1']);
    expect(combos[1].values).toEqual({ Size: 'S', Color: 'Blue' });
  });

  it('keeps the key of an existing row when an option is renamed', () => {
    const before = indexedCombinations([{ name: 'Size', values: ['S'] }]);
    const after = indexedCombinations([{ name: 'Length', values: ['S', 'M'] }]);
    expect(after[0].key).toBe(before[0].key);
  });

  it('gives one empty combination without options', () => {
    expect(indexedCombinations([])).toEqual([{ key: '', values: {} }]);
  });
});
