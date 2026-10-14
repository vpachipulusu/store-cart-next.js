import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buttonVariants } from '@/components/ui/button';
import { badgeVariants } from '@/components/ui/badge';

/** KAN-176: 44px touch targets and one navy focus ring defined in globals.css. */

const read = (rel: string) => readFileSync(resolve(__dirname, '../../..', rel), 'utf8');

describe('Button sizes', () => {
  it.each([
    ['default', 'h-11'],
    ['lg', 'h-12'],
    ['sm', 'h-10'],
  ] as const)('size %s uses %s', (size, height) => {
    expect(buttonVariants({ size })).toContain(height);
  });

  it('icon is 44x44', () => {
    expect(buttonVariants({ size: 'icon' })).toContain('h-11 w-11');
  });
});

describe('Single focus ring', () => {
  it('has no per-component ring classes on Button, Input or Badge', () => {
    const input = read('components/ui/input.tsx');
    for (const classes of [buttonVariants(), badgeVariants(), input]) {
      expect(classes).not.toMatch(/(focus|focus-visible):ring/);
    }
  });

  it('defines the focus-visible outline once with --ring', () => {
    const css = read('app/globals.css');
    expect(css).toMatch(/\*:focus-visible\s*\{\s*outline: 3px solid hsl\(var\(--ring\)\);/);
    expect(css).not.toContain('ring-ring/50');
  });
});
