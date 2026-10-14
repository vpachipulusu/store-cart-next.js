import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { THEME_PRESETS, type ThemeModeVariables } from '@/config/themes';
import { contrast } from '../helpers/contrast';

type Mode = 'light' | 'dark';
type TokenName = keyof ThemeModeVariables;

const TEXT_MIN = 4.5;
const UI_MIN = 3;

interface Pair {
  label: string;
  fg: (v: ThemeModeVariables, mode: Mode) => string;
  bg: (v: ThemeModeVariables, mode: Mode) => string;
  min: number;
}

const tok = (name: TokenName) => (v: ThemeModeVariables) => v[name];
/** Text colour used on the inverse `--feature` panel (ivory in light, foreground in dark). */
const featureText = (v: ThemeModeVariables, mode: Mode) =>
  mode === 'light' ? v['--background'] : v['--foreground'];

const text = (label: string, fg: TokenName, bg: TokenName): Pair => ({
  label,
  fg: tok(fg),
  bg: tok(bg),
  min: TEXT_MIN,
});
const ui = (label: string, fg: TokenName, bg: TokenName): Pair => ({
  label,
  fg: tok(fg),
  bg: tok(bg),
  min: UI_MIN,
});

const PAIRS: Pair[] = [
  text('foreground on background', '--foreground', '--background'),
  text('card-foreground on card', '--card-foreground', '--card'),
  text('primary-foreground on primary', '--primary-foreground', '--primary'),
  text('muted text on background', '--muted-foreground', '--background'),
  text('muted text on card', '--muted-foreground', '--card'),
  text('muted text on secondary', '--muted-foreground', '--secondary'),
  text('accent-foreground on accent', '--accent-foreground', '--accent'),
  text('cta-foreground on cta', '--cta-foreground', '--cta'),
  text('cta-foreground on cta-hover', '--cta-foreground', '--cta-hover'),
  text('accent-ink on background', '--accent-ink', '--background'),
  text('accent-ink on card', '--accent-ink', '--card'),
  text('accent-ink on secondary', '--accent-ink', '--secondary'),
  text('destructive-foreground on destructive', '--destructive-foreground', '--destructive'),
  text('good text on good tint', '--good-fg', '--good-bg'),
  text('warn text on warn tint', '--warn-fg', '--warn-bg'),
  text('crit text on crit tint', '--crit-fg', '--crit-bg'),
  text('info text on info tint', '--info-fg', '--info-bg'),
  text('crit text on background', '--crit-fg', '--background'),
  text('crit text on card', '--crit-fg', '--card'),
  { label: 'feature text on feature', fg: featureText, bg: tok('--feature'), min: TEXT_MIN },
  ui('control edge (input) on background', '--input', '--background'),
  ui('control edge (input) on card', '--input', '--card'),
  ui('focus ring on background', '--ring', '--background'),
  ui('focus ring on card', '--ring', '--card'),
  ui('cta on feature', '--cta', '--feature'),
];

const MODES: Mode[] = ['light', 'dark'];

describe.each(Object.keys(THEME_PRESETS))('theme-contrast: %s preset', (presetName) => {
  describe.each(MODES)('%s mode', (mode) => {
    const vars = THEME_PRESETS[presetName][mode];

    it.each(PAIRS.map((p) => [p.label, p] as const))('%s', (_label, pair) => {
      const fg = pair.fg(vars, mode);
      const bg = pair.bg(vars, mode);
      expect(fg, 'foreground token must be defined').toBeTruthy();
      expect(bg, 'background token must be defined').toBeTruthy();
      expect(contrast(fg, bg)).toBeGreaterThanOrEqual(pair.min);
    });
  });
});

describe('contrast helper', () => {
  it('matches known values from the design plan', () => {
    expect(contrast('0 0% 100%', '0 0% 0%')).toBeCloseTo(21, 1);
    // navy on ivory (plan section 4.3: 17.17, computed from rounded hex; HSL gives ~17.2)
    expect(contrast('222 47% 11%', '40 33% 98%')).toBeCloseTo(17.17, 0);
    // white on the old gold CTA (plan: 2.11), the bug this story removes
    expect(contrast('0 0% 100%', '38 65% 60%')).toBeCloseTo(2.11, 1);
  });
});

describe('globals.css matches the luxury preset (no-JS fallback)', () => {
  const css = readFileSync(resolve(__dirname, '../../app/globals.css'), 'utf8');

  function parseBlock(selector: ':root' | '.dark'): Record<string, string> {
    const start = css.indexOf(`${selector} {`);
    expect(start, `${selector} block present`).toBeGreaterThanOrEqual(0);
    const end = css.indexOf('}', start);
    const out: Record<string, string> = {};
    for (const m of css.slice(start, end).matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
      out[m[1]] = m[2].trim();
    }
    return out;
  }

  it.each([
    [':root', 'light'],
    ['.dark', 'dark'],
  ] as const)('%s equals THEME_PRESETS.luxury.%s for every preset token', (selector, mode) => {
    const block = parseBlock(selector);
    for (const [name, value] of Object.entries(THEME_PRESETS.luxury[mode])) {
      expect(block[name], `${selector} ${name}`).toBe(value);
    }
  });
});
