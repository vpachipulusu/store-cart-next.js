import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Button, buttonVariants } from '@/components/ui/button';

/** KAN-174: white text on the gold accent fails contrast; use the --cta pair instead. */

const SRC_ROOT = resolve(__dirname, '../../..');
const BANNED = 'bg-theme-accent text-white';

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      return name === '__tests__' ? [] : sourceFiles(full);
    }
    return /\.(tsx?|css)$/.test(name) ? [full] : [];
  });
}

describe('Button accent variant', () => {
  it('renders the cta fill, foreground and hover classes', () => {
    render(<Button variant="accent">Start free</Button>);

    const button = screen.getByRole('button', { name: 'Start free' });
    expect(button).toHaveClass('bg-cta', 'text-cta-foreground', 'hover:bg-cta-hover');
  });

  it('does not use white-on-accent or a coloured glow', () => {
    const classes = buttonVariants({ variant: 'accent' });

    expect(classes).not.toContain('text-white');
    expect(classes).not.toContain('bg-theme-accent');
    expect(classes).not.toMatch(/shadow-theme-accent/);
  });
});

describe('white-on-gold regression guard', () => {
  it(`has no "${BANNED}" in src`, () => {
    const offenders = sourceFiles(SRC_ROOT).filter((file) =>
      readFileSync(file, 'utf8').includes(BANNED)
    );

    expect(offenders).toEqual([]);
  });
});
