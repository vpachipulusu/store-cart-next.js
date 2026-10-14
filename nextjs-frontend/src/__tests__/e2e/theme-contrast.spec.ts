import { test, expect } from './helpers/fixtures';
import { waitForPageReady } from './helpers/e2e-utils';
import { contrast } from '../helpers/contrast';

/**
 * KAN-173: the runtime theme tokens (injected by the root layout from the admin
 * preset, not only globals.css) must keep the CTA pair readable in both colour
 * schemes. Reads the computed custom properties from the live page.
 */

const PAGES = ['/', '/login'] as const;
const SCHEMES = ['light', 'dark'] as const;
const TEXT_MIN = 4.5;

for (const path of PAGES) {
  for (const scheme of SCHEMES) {
    test(`CTA tokens meet 4.5:1 on ${path} (${scheme})`, async ({ page }) => {
      // The theme provider defaults to the system scheme.
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await waitForPageReady(page);

      const tokens = await page.evaluate(() => {
        const style = getComputedStyle(document.documentElement);
        return {
          cta: style.getPropertyValue('--cta').trim(),
          ctaForeground: style.getPropertyValue('--cta-foreground').trim(),
          ctaHover: style.getPropertyValue('--cta-hover').trim(),
          isDark: document.documentElement.classList.contains('dark'),
        };
      });

      expect(tokens.isDark).toBe(scheme === 'dark');
      expect(tokens.cta).not.toBe('');
      expect(tokens.ctaForeground).not.toBe('');
      expect(contrast(tokens.ctaForeground, tokens.cta)).toBeGreaterThanOrEqual(TEXT_MIN);
      expect(contrast(tokens.ctaForeground, tokens.ctaHover)).toBeGreaterThanOrEqual(TEXT_MIN);
    });
  }
}
