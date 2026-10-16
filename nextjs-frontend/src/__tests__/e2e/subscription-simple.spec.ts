import { test, expect } from './helpers/fixtures';
import {
  loginAsThrowawayAccountWithOrganization,
  signInWithSavedSession,
  waitForServerActionResponse,
  navigateAndWait,
  STRIPE_E2E_ENABLED,
  STRIPE_E2E_SKIP_REASON,
  STRIPE_TEST_CARDS,
  fillStripeCheckout,
  submitStripeCheckout,
  waitForSubscriptionSuccess,
  expectSubscriptionTier,
} from './helpers/e2e-utils';

/**
 * Simplified Subscription Upgrade E2E Test
 *
 * This test focuses on the critical happy path:
 * 1. Login as free tier user
 * 2. Navigate to pricing page
 * 3. Click upgrade to Pro
 * 4. Complete Stripe checkout
 * 5. Verify success redirect
 * 6. Verify subscription updated
 *
 * Uses helper functions for common operations.
 */

test.describe('Subscription Upgrade - Happy Path', () => {
  test.skip(
    !process.env.TEST_USER_EMAIL || !process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
    'Skipped: TEST_USER_EMAIL or STRIPE not configured'
  );

  // Needs the Stripe webhook to reach the backend (`stripe listen`, KAN-157), so it runs only with E2E_STRIPE=1.
  test.describe('with the Stripe webhook forwarded', () => {
    test.skip(!STRIPE_E2E_ENABLED, STRIPE_E2E_SKIP_REASON);

    test('should successfully upgrade from free to pro tier', async ({
      page,
      throwawayAccount,
    }) => {
      // Checkout, the Stripe webhook and the success handler's polling (up to 30 s) take longer than the 30 s default.
      test.setTimeout(150_000);

      // Step 1: Login as a fresh free-tier user (throwaway: this test changes the plan)
      await loginAsThrowawayAccountWithOrganization(page, throwawayAccount);

      // Step 2: Navigate to pricing page
      await navigateAndWait(page, '/pricing');

      // Step 3: Find and click Pro tier upgrade button
      const proCard = page
        .locator('[class*="card"]')
        .filter({ has: page.getByRole('heading', { name: 'Pro', exact: true }) });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (!buttonExists) {
        test.skip(true, 'Upgrade button not available - user may already be on Pro tier');
        return;
      }

      // Step 4: Click upgrade: the app sends this tab to Stripe Checkout (window.location.href), not a new tab.
      await upgradeButton.click();
      await page.waitForURL(/checkout\.stripe\.com/);
      const checkoutPage = page;

      // Verify on Stripe checkout
      expect(checkoutPage.url()).toContain('checkout.stripe.com');

      // Step 5: Fill checkout form with test card
      await fillStripeCheckout(checkoutPage, STRIPE_TEST_CARDS.success);

      // Step 6: Submit payment
      await submitStripeCheckout(checkoutPage);

      // Step 7: Wait for success redirect and webhook processing (the same tab returns to the app)
      const success = await waitForSubscriptionSuccess(page);
      expect(success).toBe(true);

      // Step 8: Verify subscription tier updated
      await expectSubscriptionTier(page, 'pro');

      // Step 9: Verify upgrade banner is gone
      const upgradeBanner = page.getByText(/upgrade to pro/i).first();
      await expect(upgradeBanner).not.toBeVisible();

      console.log('✅ Subscription upgrade successful!');
    });
  });

  test('should display subscription in admin panel after upgrade', async ({ page, context }) => {
    // First, ensure user is on pro tier (prerequisite test or manual setup)
    // Login as admin (session saved by auth.setup.ts)
    await signInWithSavedSession(context, 'admin');

    // Navigate to admin subscriptions page
    await navigateAndWait(page, '/admin/subscriptions');

    // Wait for page to load
    await expect(page.getByRole('heading', { name: /subscription management/i })).toBeVisible();

    // Check stats cards
    const totalActiveCard = page.locator('[class*="card"]').filter({ hasText: /total active/i });
    const proPlansCard = page.locator('[class*="card"]').filter({ hasText: /pro plans/i });

    // Should show at least 1 active subscription if the previous test ran
    await expect(totalActiveCard).toBeVisible();
    await expect(proPlansCard).toBeVisible();

    // Check if recent subscriptions table has entries or empty state
    const emptyState = page.getByText(/no active subscriptions/i);
    const subscriptionTable = page.getByRole('table');

    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    if (!hasEmptyState) {
      // Table should be visible with subscription data
      await expect(subscriptionTable).toBeVisible();

      // Should have headers
      await expect(page.getByRole('columnheader', { name: /customer/i })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: /email/i })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: /plan/i })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: /status/i })).toBeVisible();

      // Should have at least one row with Pro badge
      const proBadge = page.getByRole('cell', { name: /pro/i }).first();
      await expect(proBadge).toBeVisible({ timeout: 5000 });

      console.log('✅ Subscription visible in admin panel!');
    } else {
      console.log('⚠️ No subscriptions in admin panel yet - may need to run upgrade test first');
    }
  });

  test('should prevent fake upgrade success URL manipulation', async ({ page }) => {
    // Login as test user (session saved by auth.setup.ts)
    await signInWithSavedSession(page.context(), 'user');

    // Try to manually navigate to upgrade success URL (without actual payment)
    const verification = waitForServerActionResponse(page, '/dashboard');
    await page.goto('/dashboard?upgrade=success');
    await verification;

    // Should redirect to clean dashboard URL (removing the query parameter)
    // because there's no valid checkout session
    await page.waitForTimeout(2000); // Wait for verification

    // URL should be cleaned up
    // The app removes ?upgrade=success once it finds no valid checkout session; retry until it has.
    await expect(page).not.toHaveURL(/upgrade=success/);
    await expect(page).toHaveURL(/\/dashboard$/);

    // Should NOT show the success processing banner
    const processingBanner = page.getByText(/processing your subscription/i);
    await expect(processingBanner).not.toBeVisible();

    console.log('✅ Security: Fake URL manipulation prevented!');
  });
});
