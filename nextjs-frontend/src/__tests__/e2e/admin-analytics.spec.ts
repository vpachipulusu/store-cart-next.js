import { test, expect } from './helpers/fixtures';
import { STORAGE_STATE, waitForPageReady } from './helpers/e2e-utils';

/**
 * Admin analytics smoke tests (KAN-119): the analytics, settings and subscriptions pages load their data from
 * the analytics API, and the Stripe reconciliation panel answers (a report, or a curated error when the test
 * environment has no usable Stripe key).
 *
 * Needs an admin account with the `*` grant (TEST_ADMIN_EMAIL); skipped when it is not configured.
 */

test.describe('Admin analytics (KAN-119)', () => {
  test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
  test.use({ storageState: STORAGE_STATE.admin });

  test('analytics page shows platform figures and revenue', async ({ page }) => {
    await page.goto('/admin/analytics');
    await waitForPageReady(page);

    await expect(page.getByRole('heading', { name: /^analytics$/i, level: 1 })).toBeVisible();
    await expect(page.getByLabel('Users', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Organisations', { exact: true })).toBeVisible();
    await expect(page.getByLabel('MRR', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Stores by status' })).toBeVisible();
    await expect(page.getByText('Not available yet')).toHaveCount(0);
  });

  test('settings page shows the system stats', async ({ page }) => {
    await page.goto('/admin/settings');
    await waitForPageReady(page);

    await expect(page.getByRole('heading', { name: /^settings$/i, level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'System stats' })).toBeVisible();
    await expect(page.getByText('Audit log entries')).toBeVisible();
    await expect(page.getByText('Platform admins')).toBeVisible();
  });

  test('subscriptions page runs the Stripe reconciliation panel', async ({ page }) => {
    await page.goto('/admin/subscriptions');
    await waitForPageReady(page);

    await expect(page.getByRole('heading', { name: /subscription management/i })).toBeVisible();
    await expect(page.getByLabel('MRR', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Stripe reconciliation' })).toBeVisible();

    await page.getByRole('button', { name: /check against stripe/i }).click();

    // A report when Stripe answers, a curated alert when it does not; either way the panel works.
    await expect(
      page.getByText(/Read \d+ Stripe subscriptions/).or(page.getByRole('alert'))
    ).toBeVisible({ timeout: 30_000 });
  });
});
