import { test, expect } from './helpers/fixtures';
import {
  ensureAccountHasStore,
  loginAsThrowawayAccount,
  navigateAndWait,
} from './helpers/e2e-utils';

/**
 * Stripe Connect onboarding section on the dashboard settings page (KAN-67).
 *
 * The onboarding itself happens on Stripe, so these specs stop at our side of the hand-off: the status panel, the
 * Start button and the return markers. Whether the click reaches Stripe depends on the backend's Stripe key
 * (test mode) and on Connect being enabled for that Stripe account, so the click test accepts either the hosted link
 * or a curated error, and fails on anything raw.
 */

test.describe('Settings - Stripe Connect payments', () => {
  test('a new organisation sees the account as not set up with a Start button', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await ensureAccountHasStore(page, `e2e-connect-${Date.now()}`);

    await navigateAndWait(page, '/dashboard/settings');

    const panel = page.getByRole('region', { name: 'Payments' });
    await expect(panel).toBeVisible();
    await expect(panel.getByText('Not set up')).toBeVisible();
    await expect(panel.getByText('Not enabled')).toHaveCount(2);
    await expect(panel.getByText(/checkout stays off/i)).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Start onboarding' })).toBeEnabled();
  });

  test('Start onboarding either opens the Stripe-hosted link or shows a curated error', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await ensureAccountHasStore(page, `e2e-connect-${Date.now()}`);
    await navigateAndWait(page, '/dashboard/settings');
    const panel = page.getByRole('region', { name: 'Payments' });

    await panel.getByRole('button', { name: 'Start onboarding' }).click();

    const hosted = page
      .waitForURL(/https:\/\/connect\.stripe\.com\//, { timeout: 20_000 })
      .catch(() => undefined);
    const failed = panel.getByRole('alert');
    await Promise.race([hosted, failed.waitFor({ state: 'visible', timeout: 20_000 })]);
    if (!page.url().includes('connect.stripe.com')) {
      await expect(failed).toHaveText(
        /payment provider|not available right now|could not start payment setup|owner or admin/i
      );
      await expect(failed).not.toContainText(/acct_|sk_|stripe\.com\/v1/i);
    }
  });

  test('the return marker explains that Stripe may take a moment to confirm', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await ensureAccountHasStore(page, `e2e-connect-${Date.now()}`);

    await navigateAndWait(page, '/dashboard/settings?connect=return');

    await expect(
      page.getByRole('region', { name: 'Payments' }).getByText(/may take a moment to confirm/i)
    ).toBeVisible();
  });
});
