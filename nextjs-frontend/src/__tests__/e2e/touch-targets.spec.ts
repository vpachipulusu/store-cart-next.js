import { test, expect, type Page } from '@playwright/test';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-176: interactive controls are at least 44px high (buttons 44, large 48, inputs 44).
 * Written for local/staging runs; E2E stays off in CI.
 */

const MIN_TARGET = 44;
const PATHS = ['/login', '/signup', '/pricing'] as const;

async function shortTargets(page: Page): Promise<string[]> {
  return page.evaluate((min) => {
    const nodes = document.querySelectorAll<HTMLElement>(
      'main button, main input:not([type="hidden"]):not([type="checkbox"]), main [role="button"], header button'
    );
    return Array.from(nodes)
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && box.height < min - 0.5;
      })
      .map(
        (el) =>
          `${el.tagName.toLowerCase()} "${(el.textContent ?? '').trim().slice(0, 30)}" ${el.getBoundingClientRect().height}px`
      );
  }, MIN_TARGET);
}

for (const path of PATHS) {
  test(`controls on ${path} are at least 44px high`, async ({ page }) => {
    await page.goto(path);
    await waitForPageReady(page);
    expect(await shortTargets(page)).toEqual([]);
  });
}

test('primary button on /login is 44px and focus ring is a 3px outline', async ({ page }) => {
  await page.goto('/login');
  await waitForPageReady(page);

  const submit = page.locator('button.bg-cta').first();
  const box = await submit.boundingBox();
  expect(box?.height).toBeCloseTo(44, 0);

  const email = page.locator('input[type="email"]').first();
  expect((await email.boundingBox())?.height).toBeCloseTo(44, 0);

  await page.keyboard.press('Tab');
  await submit.focus();
  const outline = await submit.evaluate((el) => {
    const s = getComputedStyle(el);
    return { width: s.outlineWidth, offset: s.outlineOffset, style: s.outlineStyle };
  });
  expect(outline).toEqual({ width: '3px', offset: '2px', style: 'solid' });
});
