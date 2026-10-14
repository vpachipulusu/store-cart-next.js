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
  // Buttons use transition-all, so wait for the outline to finish animating in.
  await expect
    .poll(() =>
      submit.evaluate((el) => {
        const s = getComputedStyle(el);
        return { width: s.outlineWidth, offset: s.outlineOffset, style: s.outlineStyle };
      })
    )
    .toEqual({ width: '3px', offset: '2px', style: 'solid' });
});

/** Keyboard walkthrough: every Tab stop shows exactly one navy outline and no ring shadow (light mode). */
const NAVY = 'rgb(15, 23, 41)'; // --ring 222 47% 11%
const MAX_TAB_STOPS = 25;

for (const path of ['/login', '/pricing'] as const) {
  test(`tab order on ${path} shows one navy focus outline per stop`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto(path);
    await waitForPageReady(page);

    const stops: string[] = [];
    for (let i = 0; i < MAX_TAB_STOPS; i++) {
      await page.keyboard.press('Tab');
      const active = page.locator(':focus-visible');
      if ((await active.count()) === 0) break;
      // Past the page content: the TanStack devtools toggle only exists in dev builds.
      if (await active.evaluate((el) => el.className.toString().includes('tsqd'))) break;
      // Outline animates in via transition-all on buttons.
      await expect
        .poll(() => active.evaluate((el) => getComputedStyle(el).outlineWidth))
        .toBe('3px');
      const style = await active.evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          tag: el.tagName.toLowerCase(),
          color: s.outlineColor,
          style: s.outlineStyle,
          offset: s.outlineOffset,
          shadow: s.boxShadow,
        };
      });
      expect([style.color, style.style, style.offset]).toEqual([NAVY, 'solid', '2px']);
      // A Tailwind ring is a spread shadow ("0px 0px 0px 2px"); the normal shadow-sm is fine.
      expect(style.shadow).not.toMatch(/0px 0px 0px [1-9]\d*px/);
      stops.push(style.tag);
    }
    expect(stops.length).toBeGreaterThan(2);
  });
}
