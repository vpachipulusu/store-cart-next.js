import { test, expect } from '@playwright/test';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-174: the primary (accent) button on landing, login, signup and pricing must
 * meet 4.5:1 text contrast, measured from computed styles in light and dark.
 * Written for local/staging runs; E2E stays off in CI.
 */

const PATHS = ['/', '/login', '/signup', '/pricing'] as const;
const SCHEMES = ['light', 'dark'] as const;
const TEXT_MIN = 4.5;

for (const path of PATHS) {
  for (const scheme of SCHEMES) {
    test(`primary button on ${path} meets 4.5:1 (${scheme})`, async ({ page }) => {
      // The theme provider defaults to the system scheme.
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await waitForPageReady(page);

      const primary = page.locator('button.bg-cta, a.bg-cta').first();
      await expect(primary).toBeVisible();

      const ratio = await primary.evaluate((el) => {
        // Resolve any CSS colour syntax to sRGB through a canvas pixel.
        const toRgb = (css: string): number[] => {
          const ctx = document.createElement('canvas').getContext('2d', {
            willReadFrequently: true,
          })!;
          ctx.fillStyle = css;
          ctx.fillRect(0, 0, 1, 1);
          return Array.from(ctx.getImageData(0, 0, 1, 1).data);
        };
        const luminance = ([r, g, b]: number[]) => {
          const lin = (v: number) => {
            const c = v / 255;
            return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
          };
          return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
        };
        const style = getComputedStyle(el);
        const [hi, lo] = [
          luminance(toRgb(style.color)),
          luminance(toRgb(style.backgroundColor)),
        ].sort((a, b) => b - a);
        return (hi + 0.05) / (lo + 0.05);
      });

      expect(ratio).toBeGreaterThanOrEqual(TEXT_MIN);
    });
  }
}
