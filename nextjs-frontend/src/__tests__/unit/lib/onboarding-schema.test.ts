/** KAN-60: onboarding input validation and slug suggestions. */
import { describe, expect, it } from 'vitest';
import { onboardingSchema, slugify } from '@/lib/onboarding/schema';

const valid = {
  organizationName: 'Acme Ltd',
  organizationSlug: 'acme-ltd',
  storeName: 'Acme Shop',
  storeSlug: 'acme-shop',
};

describe('onboardingSchema', () => {
  it('accepts valid input and trims names', () => {
    const parsed = onboardingSchema.parse({ ...valid, storeName: '  Acme Shop  ' });
    expect(parsed.storeName).toBe('Acme Shop');
  });

  it.each([
    ['too short', 'ab'],
    ['uppercase', 'Acme'],
    ['double hyphen', 'a--b'],
    ['leading hyphen', '-abc'],
    ['spaces', 'my shop'],
    ['too long', 'a'.repeat(64)],
  ])('rejects a slug that is %s', (_label, storeSlug) => {
    expect(onboardingSchema.safeParse({ ...valid, storeSlug }).success).toBe(false);
  });

  it('rejects empty, oversized and control-character names', () => {
    expect(onboardingSchema.safeParse({ ...valid, storeName: '   ' }).success).toBe(false);
    expect(onboardingSchema.safeParse({ ...valid, storeName: 'x'.repeat(101) }).success).toBe(
      false
    );
    expect(onboardingSchema.safeParse({ ...valid, organizationName: 'a\u0000b' }).success).toBe(
      false
    );
  });
});

describe('slugify', () => {
  it('lowercases, strips accents and collapses separators', () => {
    expect(slugify('  Café  du Monde Shop! ')).toBe('cafe-du-monde-shop');
  });

  it('returns an empty string when nothing usable remains', () => {
    expect(slugify('!!!')).toBe('');
  });

  it('never exceeds the maximum length or ends with a hyphen', () => {
    const slug = slugify(`${'a'.repeat(62)} b`);
    expect(slug.length).toBeLessThanOrEqual(63);
    expect(slug.endsWith('-')).toBe(false);
  });
});
