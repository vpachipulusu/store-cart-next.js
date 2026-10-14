import { test, expect } from './helpers/fixtures';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * Motion hygiene E2E (KAN-177)
 *
 * With prefers-reduced-motion: reduce, nothing on the landing page keeps
 * running an animation, no transition lasts longer than a frame, and
 * staggered content is visible.
 */

const MAX_DURATION_S = 0.001;

test.describe('Reduced motion', () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await waitForPageReady(page);
  });

  test('no element runs a long animation or transition', async ({ page }) => {
    const offenders = await page.evaluate((max) => {
      const toSeconds = (v: string) =>
        v.split(',').map((d) => (d.trim().endsWith('ms') ? parseFloat(d) / 1000 : parseFloat(d)));
      return Array.from(document.querySelectorAll('*')).flatMap((el) => {
        const cs = getComputedStyle(el);
        const longest = Math.max(
          ...toSeconds(cs.animationDuration),
          ...toSeconds(cs.transitionDuration)
        );
        return longest > max ? [`${el.tagName.toLowerCase()}.${String(el.className)}`] : [];
      });
    }, MAX_DURATION_S);

    expect(offenders).toEqual([]);
  });

  test('stagger-children items are visible', async ({ page }) => {
    const hidden = await page.evaluate(
      () =>
        Array.from(document.querySelectorAll('.stagger-children > *')).filter(
          (el) => getComputedStyle(el).opacity !== '1'
        ).length
    );

    expect(hidden).toBe(0);
  });

  test('theme-card hover shows no glow shadow', async ({ page }) => {
    const card = page.locator('.theme-card').first();
    if ((await card.count()) === 0) test.skip(true, 'No theme-card on the landing page');
    const before = await card.evaluate((el) => getComputedStyle(el).boxShadow);
    await card.hover();
    const after = await card.evaluate((el) => getComputedStyle(el).boxShadow);

    expect(after).toBe(before);
  });
});
