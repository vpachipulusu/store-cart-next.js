import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, '../../app/globals.css'), 'utf8');

/** Returns the body of the first `@media (prefers-reduced-motion: reduce) { ... }` block. */
function reducedMotionBlock(source: string): string {
  const start = source.indexOf('@media (prefers-reduced-motion: reduce)');
  expect(start).toBeGreaterThan(-1);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) {
      return source.slice(source.indexOf('{', start) + 1, i);
    }
  }
  throw new Error('Unterminated reduced-motion block');
}

describe('motion hygiene (KAN-177)', () => {
  it('disables animation and transition durations under reduced motion', () => {
    const block = reducedMotionBlock(css);
    expect(block).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(block).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
  });

  it('keeps stagger-children visible and un-animated under reduced motion', () => {
    const block = reducedMotionBlock(css);
    expect(block).toMatch(/\.stagger-children\s*>\s*\*\s*{[^}]*opacity:\s*1/);
    expect(block).toMatch(/\.stagger-children\s*>\s*\*\s*{[^}]*animation:\s*none/);
  });

  it('stops the shimmer under reduced motion', () => {
    expect(reducedMotionBlock(css)).toMatch(/\.shimmer-accent\s*{[^}]*animation:\s*none/);
  });

  it('keeps the stagger-children reveal for normal motion', () => {
    expect(css).toMatch(/\.stagger-children\s*>\s*\*\s*{[^}]*animation:\s*reveal-up/);
  });

  it('removes the accent glow hovers from theme-card and theme-border', () => {
    expect(css).not.toMatch(/\.theme-card:hover/);
    expect(css).not.toMatch(/\.theme-border:hover/);
    expect(css).not.toMatch(/box-shadow:[^;]*theme-accent/);
  });

  it('limits reveal travel to 10px', () => {
    const keyframes = css.match(/@keyframes reveal-up\s*{[\s\S]*?}\s*}/)?.[0] ?? '';
    expect(keyframes).toContain('translateY(10px)');
    expect(keyframes).not.toContain('translateY(20px)');
  });
});
