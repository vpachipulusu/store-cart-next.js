import { test, expect, type Page } from '@playwright/test';
import { STORAGE_STATE, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-217: the merchant shell. A 240px sidebar from 900px up, a bottom tab bar with a More sheet below it, and every
 * dashboard route reachable at 375px and 1440px. Written for local runs (E2E stays off in CI).
 */

const ROUTES = [
  { label: 'Overview', path: '/dashboard', inMore: false },
  { label: 'Billing', path: '/dashboard/settings/billing', inMore: false },
  { label: 'Settings', path: '/dashboard/settings', inMore: false },
  { label: 'Profile', path: '/dashboard/profile', inMore: true },
  { label: 'Security', path: '/dashboard/security', inMore: true },
] as const;

const PHONE = { width: 375, height: 812 };
const DESKTOP = { width: 1440, height: 900 };

async function open(page: Page, path: string) {
  await page.goto(path);
  await waitForPageReady(page);
}

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe('Dashboard shell', () => {
  test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
  test.use({ storageState: STORAGE_STATE.user });

  test.describe('at 1440px', () => {
    test.use({ viewport: DESKTOP });

    test('shows a 240px sidebar with landmarks and no tab bar', async ({ page }) => {
      await open(page, '/dashboard');

      const aside = page.getByRole('complementary', { name: 'Workspace' });
      await expect(aside).toBeVisible();
      expect((await aside.boundingBox())?.width).toBeCloseTo(240, 0);
      await expect(aside.getByRole('navigation', { name: 'Main' })).toBeVisible();
      await expect(page.getByRole('main')).toBeVisible();
      await expect(page.getByRole('button', { name: 'More' })).toBeHidden();
      await expectNoHorizontalScroll(page);
    });

    test('the skip link is the first tab stop and moves focus to main', async ({ page }) => {
      await open(page, '/dashboard');
      await page.keyboard.press('Tab');

      await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(page.locator('#main-content')).toBeFocused();
    });

    for (const route of ROUTES) {
      test(`reaches ${route.label} from the sidebar with aria-current`, async ({ page }) => {
        await open(page, '/dashboard');
        const nav = page.getByRole('navigation', { name: 'Main' });
        await nav.getByRole('link', { name: route.label, exact: true }).click();
        await expect(page).toHaveURL(new RegExp(`${route.path}$`));

        const current = nav.locator('[aria-current="page"]');
        await expect(current).toHaveCount(1);
        await expect(current).toHaveText(route.label);
        const link = nav.getByRole('link', { name: route.label, exact: true });
        expect((await link.boundingBox())?.height).toBeGreaterThanOrEqual(44);
      });
    }
  });

  test.describe('at 375px', () => {
    test.use({ viewport: PHONE });

    test('shows a bottom tab bar and no sidebar', async ({ page }) => {
      await open(page, '/dashboard');

      await expect(page.getByRole('complementary', { name: 'Workspace' })).toBeHidden();
      const tabs = page.getByRole('navigation', { name: 'Main' });
      await expect(tabs).toBeVisible();
      expect((await tabs.boundingBox())?.height).toBeCloseTo(56, 0);
      await expectNoHorizontalScroll(page);
    });

    for (const route of ROUTES) {
      test(`reaches ${route.label} from the tab bar${route.inMore ? ' via More' : ''}`, async ({
        page,
      }) => {
        await open(page, '/dashboard');
        const tabs = page.getByRole('navigation', { name: 'Main' });

        if (route.inMore) {
          await tabs.getByRole('button', { name: 'More' }).click();
          const sheet = page.getByRole('dialog', { name: 'More' });
          await sheet.getByRole('link', { name: route.label, exact: true }).click();
          await expect(sheet).toBeHidden();
        } else {
          await tabs.getByRole('link', { name: route.label, exact: true }).click();
        }
        await expect(page).toHaveURL(new RegExp(`${route.path}$`));
        await expect(page.getByRole('main')).toBeVisible();
        await expectNoHorizontalScroll(page);
      });
    }

    test('the More sheet traps focus and gives it back on Escape', async ({ page }) => {
      await open(page, '/dashboard');
      const more = page.getByRole('button', { name: 'More' });
      await more.click();

      const sheet = page.getByRole('dialog', { name: 'More' });
      await expect(sheet).toBeVisible();
      for (let i = 0; i < 6; i += 1) {
        await page.keyboard.press('Tab');
        expect(await sheet.evaluate((el) => el.contains(document.activeElement))).toBe(true);
      }

      await page.keyboard.press('Escape');
      await expect(sheet).toBeHidden();
      await expect(more).toBeFocused();
    });

    test('marks the tab for the current page', async ({ page }) => {
      await open(page, '/dashboard/settings/billing');
      const tabs = page.getByRole('navigation', { name: 'Main' });
      await expect(tabs.locator('[aria-current="page"]')).toHaveText('Billing');
    });
  });
});
