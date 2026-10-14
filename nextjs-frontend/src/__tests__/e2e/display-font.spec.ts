import { test, expect } from './helpers/fixtures';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * Display font E2E (KAN-175)
 *
 * - h1 renders in the Fraunces display font
 * - body text keeps the admin-selectable body font (never Fraunces)
 * - landing page layout shift stays below the 0.1 CLS budget
 */

const CLS_BUDGET = 0.1;

test.describe('Display font', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForPageReady(page);
    await page.evaluate(() => document.fonts.ready);
  });

  test('h1 computed font-family starts with Fraunces', async ({ page }) => {
    const family = await page
      .locator('h1')
      .first()
      .evaluate((el) => getComputedStyle(el).fontFamily);

    expect(family.replace(/["']/g, '')).toMatch(/^Fraunces\b/);
  });

  test('body text keeps the body font, not the display font', async ({ page }) => {
    const [bodyFamily, paragraphFamily] = await page.evaluate(() => {
      const paragraph = document.querySelector('p');
      return [
        getComputedStyle(document.body).fontFamily,
        paragraph ? getComputedStyle(paragraph).fontFamily : '',
      ];
    });

    expect(bodyFamily).not.toContain('Fraunces');
    expect(paragraphFamily).not.toContain('Fraunces');
    expect(bodyFamily).toContain('system-ui');
  });

  test('landing cumulative layout shift is below 0.1', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'layout-shift entries are Chromium-only');

    await page.goto('/');
    await waitForPageReady(page);
    await page.evaluate(() => document.fonts.ready);

    const cls = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          let total = 0;
          const observer = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              const shift = entry as PerformanceEntry & {
                value: number;
                hadRecentInput: boolean;
              };
              if (!shift.hadRecentInput) total += shift.value;
            }
          });
          observer.observe({ type: 'layout-shift', buffered: true });
          setTimeout(() => {
            observer.disconnect();
            resolve(total);
          }, 1500);
        })
    );

    expect(cls).toBeLessThan(CLS_BUDGET);
  });
});
