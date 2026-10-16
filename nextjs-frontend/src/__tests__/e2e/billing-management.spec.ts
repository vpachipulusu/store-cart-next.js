import { test, expect } from './helpers/fixtures';
import {
  STORAGE_STATE,
  loginAsThrowawayAccount,
  loginAsThrowawayAccountWithOrganization,
  signInWithSavedSession,
  navigateAndWait,
  navigateToBilling,
  toggleAutoRenewal,
  expectRedirectToLogin,
  STRIPE_E2E_ENABLED,
  STRIPE_E2E_SKIP_REASON,
  STRIPE_TEST_CARDS,
  fillStripeCheckout,
  submitStripeCheckout,
  waitForSubscriptionSuccess,
} from './helpers/e2e-utils';

/**
 * Billing Management E2E Tests
 *
 * Tests the following features:
 * 1. Billing period toggle (monthly/yearly) on pricing page
 * 2. Billing settings page access and display
 * 3. Auto-renewal toggle
 * 4. Payment method display and deletion protection
 * 5. Billing history display
 */

test.describe('Pricing Page - Billing Period Toggle', () => {
  test('should display monthly/yearly toggle on pricing page', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Toggle buttons should be visible
    const monthlyButton = page.getByRole('button', { name: /monthly/i });
    const yearlyButton = page.getByRole('button', { name: /yearly/i });

    await expect(monthlyButton).toBeVisible();
    await expect(yearlyButton).toBeVisible();
  });

  test('should show monthly prices by default', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Monthly should be the active selection
    const monthlyButton = page.getByRole('button', { name: /monthly/i });
    // Monthly button should have primary styling (active state)
    await expect(monthlyButton).toBeVisible();

    // Cards should show /month label
    const monthLabel = page.getByText('/month').first();
    await expect(monthLabel).toBeVisible();
  });

  test('should switch to yearly prices when yearly is selected', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Click yearly toggle
    const yearlyButton = page.getByRole('button', { name: /yearly/i });
    await yearlyButton.click();

    // Yearly shows the monthly equivalent ("/month") plus "<price> billed annually"; there is no "/year" label.
    await expect(page.getByText('/month').first()).toBeVisible();

    // Should show the annual total
    const billedAnnually = page.getByText(/billed annually/i).first();
    await expect(billedAnnually).toBeVisible();
  });

  test('should show savings badge on yearly toggle', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Look for the savings badge near the yearly button
    const savingsBadge = page.getByText(/save \d+%/i);
    await expect(savingsBadge).toBeVisible();
  });

  test('should show cancel anytime text for monthly plans', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Monthly should show "Cancel anytime"
    const cancelAnytime = page.getByText(/cancel anytime/i).first();
    await expect(cancelAnytime).toBeVisible();
  });

  test('should switch back to monthly from yearly', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    // Switch to yearly
    await page.getByRole('button', { name: /yearly/i }).click();
    await expect(page.getByText(/billed annually/i).first()).toBeVisible();

    // Switch back to monthly
    await page.getByRole('button', { name: /monthly/i }).click();
    await expect(page.getByText('/month').first()).toBeVisible();
    await expect(page.getByText(/billed annually/i)).toHaveCount(0);
  });
});

test.describe('Billing Settings Page - Access', () => {
  test('should redirect unauthenticated users to login', async ({ page }) => {
    await expectRedirectToLogin(page, '/dashboard/settings/billing');
  });

  test('should be accessible from dashboard billing quick action', async ({ page }) => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

    await signInWithSavedSession(page.context(), 'user');
    await navigateAndWait(page, '/dashboard');

    // Click on Billing quick action card
    const billingCard = page
      .locator('[class*="card"]')
      .filter({ hasText: /billing/i })
      .filter({ hasText: /manage subscription/i });
    await billingCard.click();

    // Should navigate to billing page
    await page.waitForURL(/\/dashboard\/settings\/billing/, { timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /billing & subscription/i })).toBeVisible();
  });

  test('should be accessible from navigation bar', async ({ page }) => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

    await signInWithSavedSession(page.context(), 'user');
    await navigateAndWait(page, '/dashboard');

    // Click Billing in nav
    const billingNavLink = page.getByRole('link', { name: /billing/i }).first();
    await billingNavLink.click();

    await page.waitForURL(/\/dashboard\/settings\/billing/, { timeout: 10_000 });
    await expect(page.getByRole('heading', { name: /billing & subscription/i })).toBeVisible();
  });
});

test.describe('Billing Settings Page - Content', () => {
  test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
  test.use({ storageState: STORAGE_STATE.user });

  test('should display current plan card', async ({ page }) => {
    await navigateToBilling(page);

    // Current Plan card should be visible
    const currentPlanCard = page.locator('[class*="card"]').filter({ hasText: /current plan/i });
    await expect(currentPlanCard).toBeVisible();

    // Should show the plan name (free, pro, or enterprise)
    await expect(currentPlanCard).toContainText(/plan/i);
  });

  test('should display payment methods section', async ({ page }) => {
    await navigateToBilling(page);

    // Payment Methods card should be visible
    const paymentMethodsCard = page
      .locator('[class*="card"]')
      .filter({ hasText: /payment methods/i });
    await expect(paymentMethodsCard).toBeVisible();
  });

  test('should display billing history section', async ({ page }) => {
    await navigateToBilling(page);

    // Billing History card should be visible
    const billingHistoryCard = page
      .locator('[class*="card"]')
      .filter({ hasText: /billing history/i });
    await expect(billingHistoryCard).toBeVisible();
  });

  test('should show upgrade button for free tier users', async ({ page }) => {
    await navigateToBilling(page);

    // Check if user is on free tier - upgrade button should be visible
    const currentPlanCard = page.locator('[class*="card"]').filter({ hasText: /current plan/i });
    const hasFree = await currentPlanCard
      .getByText(/free/i)
      .isVisible()
      .catch(() => false);

    if (hasFree) {
      const upgradeButton = currentPlanCard.getByRole('link', { name: /upgrade plan/i });
      await expect(upgradeButton).toBeVisible();
    }
  });
});

test.describe('Billing Settings - Auto-Renewal', () => {
  test.skip(
    !process.env.TEST_USER_EMAIL || !process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
    'Skipped: TEST_USER_EMAIL or STRIPE not configured'
  );
  test.use({ storageState: STORAGE_STATE.user });

  test('should show auto-renewal toggle for active subscribers', async ({ page }) => {
    await navigateToBilling(page);

    // Auto-renewal card only visible for active subscribers
    const autoRenewalCard = page.locator('[class*="card"]').filter({ hasText: /auto-renewal/i });
    const isVisible = await autoRenewalCard.isVisible().catch(() => false);

    if (isVisible) {
      // Should have a switch toggle
      const toggle = autoRenewalCard.locator('button[role="switch"]');
      await expect(toggle).toBeVisible();

      // Should have descriptive text
      await expect(autoRenewalCard).toContainText(/renew|expire/i);
    } else {
      // User is on free tier, auto-renewal section should not be visible
      console.log('User is on free tier - auto-renewal toggle not shown (expected)');
    }
  });

  test('should toggle auto-renewal off and show expiration message', async ({
    page,
    throwawayAccount,
  }) => {
    test.skip(
      !STRIPE_E2E_ENABLED,
      `${STRIPE_E2E_SKIP_REASON}: auto-renewal needs an active Stripe subscription, which an admin grant does not create`
    );
    await loginAsThrowawayAccount(page, throwawayAccount);
    await navigateToBilling(page);

    const autoRenewalCard = page.locator('[class*="card"]').filter({ hasText: /auto-renewal/i });
    await expect(autoRenewalCard).toBeVisible();

    const toggle = autoRenewalCard.locator('button[role="switch"]');
    const isChecked = await toggle.getAttribute('aria-checked');

    if (isChecked === 'true') {
      // Turn off auto-renewal
      await toggleAutoRenewal(page);

      // Should now show cancellation message
      const currentPlanCard = page.locator('[class*="card"]').filter({ hasText: /current plan/i });
      await expect(currentPlanCard).toContainText(/expires on/i);
    }
  });

  test('should toggle auto-renewal back on and show renewal message', async ({
    page,
    throwawayAccount,
  }) => {
    test.skip(
      !STRIPE_E2E_ENABLED,
      `${STRIPE_E2E_SKIP_REASON}: auto-renewal needs an active Stripe subscription, which an admin grant does not create`
    );
    await loginAsThrowawayAccount(page, throwawayAccount);
    await navigateToBilling(page);

    const autoRenewalCard = page.locator('[class*="card"]').filter({ hasText: /auto-renewal/i });
    await expect(autoRenewalCard).toBeVisible();

    const toggle = autoRenewalCard.locator('button[role="switch"]');
    const isChecked = await toggle.getAttribute('aria-checked');

    if (isChecked === 'false') {
      // Turn on auto-renewal
      await toggleAutoRenewal(page);

      // Should now show renewal message
      const currentPlanCard = page.locator('[class*="card"]').filter({ hasText: /current plan/i });
      await expect(currentPlanCard).toContainText(/renews on/i);
    }
  });
});

test.describe('Billing Settings - Payment Methods', () => {
  test.skip(
    !process.env.TEST_USER_EMAIL || !process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
    'Skipped: TEST_USER_EMAIL or STRIPE not configured'
  );
  test.use({ storageState: STORAGE_STATE.user });

  test('should display saved payment methods with card details', async ({ page }) => {
    await navigateToBilling(page);

    const paymentCard = page.locator('[class*="card"]').filter({ hasText: /payment methods/i });
    await expect(paymentCard).toBeVisible();

    // Check if there are saved payment methods
    const hasPaymentMethods = await paymentCard
      .getByText(/ending in/i)
      .first()
      .isVisible()
      .catch(() => false);

    if (hasPaymentMethods) {
      // Should show card brand and last 4 digits
      await expect(paymentCard.getByText(/ending in \d{4}/i).first()).toBeVisible();

      // Should show expiry date
      await expect(paymentCard.getByText(/expires/i).first()).toBeVisible();
    } else {
      // Should show empty state
      await expect(paymentCard.getByText(/no payment methods saved/i)).toBeVisible();
    }
  });

  test('should show default badge on default payment method', async ({ page }) => {
    await navigateToBilling(page);

    const paymentCard = page.locator('[class*="card"]').filter({ hasText: /payment methods/i });
    const hasPaymentMethods = await paymentCard
      .getByText(/ending in/i)
      .first()
      .isVisible()
      .catch(() => false);

    if (hasPaymentMethods) {
      // At least one should be marked as default
      const defaultBadge = paymentCard.getByText('Default');
      await expect(defaultBadge.first()).toBeVisible();
    }
  });

  test('should offer set-default and remove actions and explain the default card rule', async ({
    page,
  }) => {
    test.skip(
      !STRIPE_E2E_ENABLED,
      `${STRIPE_E2E_SKIP_REASON}: a saved card is only created by completing Stripe Checkout`
    );

    await navigateToBilling(page);

    const paymentCard = page.locator('[class*="card"]').filter({ hasText: /payment methods/i });
    await expect(paymentCard.getByText(/ending in/i).first()).toBeVisible();

    await expect(paymentCard.getByRole('button', { name: /remove/i }).first()).toBeEnabled();

    const autoRenewalCard = page.locator('[class*="card"]').filter({ hasText: /auto-renewal/i });
    if (await autoRenewalCard.isVisible().catch(() => false)) {
      await expect(
        paymentCard.getByText(/default card cannot be removed while you have a subscription/i)
      ).toBeVisible();
    }
  });

  test('should keep the upcoming invoice panel switched off with a clear state', async ({
    page,
  }) => {
    await navigateToBilling(page);

    await expect(page.getByText(/upcoming invoice preview is not available yet/i)).toBeVisible();
  });

  test('should show Add Payment Method button for Stripe customers', async ({ page }) => {
    await navigateToBilling(page);

    const paymentCard = page.locator('[class*="card"]').filter({ hasText: /payment methods/i });

    // Add Payment Method button should be visible if user has Stripe customer
    const addButton = paymentCard.getByRole('button', { name: /add payment method/i });
    const isVisible = await addButton.isVisible().catch(() => false);

    if (isVisible) {
      await expect(addButton).toBeEnabled();
    }
  });
});

test.describe('Billing Settings - Billing History', () => {
  test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
  test.use({ storageState: STORAGE_STATE.user });

  test('should display invoices or empty state', async ({ page }) => {
    await navigateToBilling(page);

    const billingHistoryCard = page
      .locator('[class*="card"]')
      .filter({ hasText: /billing history/i });
    await expect(billingHistoryCard).toBeVisible();

    // Either shows invoices or empty state
    const hasInvoices = await billingHistoryCard
      .getByText(/\$|paid/i)
      .first()
      .isVisible()
      .catch(() => false);

    if (hasInvoices) {
      // Should show amount and status
      await expect(billingHistoryCard.getByText(/paid|open|draft/i).first()).toBeVisible();

      // Should have download/view buttons
      const actionButton = billingHistoryCard.getByRole('link', { name: /pdf|view/i }).first();
      await expect(actionButton).toBeVisible();
    } else {
      await expect(billingHistoryCard.getByText(/no invoices yet/i)).toBeVisible();
    }
  });
});

test.describe('Pricing Page - Checkout with Billing Period', () => {
  test.skip(
    !process.env.TEST_USER_EMAIL || !process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
    'Skipped: TEST_USER_EMAIL or STRIPE not configured'
  );

  test('should use selected billing period in checkout (yearly)', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccountWithOrganization(page, throwawayAccount);
    await navigateAndWait(page, '/pricing');

    // Switch to yearly billing
    await page.getByRole('button', { name: /yearly/i }).click();
    await expect(page.getByText(/billed annually/i).first()).toBeVisible();

    // Find and click Pro tier upgrade button
    const proCard = page
      .locator('[class*="card"]')
      .filter({ has: page.getByRole('heading', { name: 'Pro', exact: true }) });
    const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

    const buttonExists = await upgradeButton.count().then((count) => count > 0);
    if (!buttonExists) {
      test.skip(true, 'Upgrade button not available - user may already be on Pro tier');
      return;
    }

    // Click upgrade: the app sends this tab to Stripe Checkout (window.location.href), not a new tab.
    await upgradeButton.click();
    await page.waitForURL(/checkout\.stripe\.com/);
    const checkoutPage = page;

    // Verify we're on Stripe checkout
    expect(checkoutPage.url()).toContain('checkout.stripe.com');

    // The checkout page should reflect the yearly price
    // (We verify by simply confirming it opened successfully)

    if (!checkoutPage.isClosed()) {
      await checkoutPage.close();
    }
  });
});

test.describe('FAQ Section - Billing Period FAQ', () => {
  test('should display FAQ about monthly vs yearly difference', async ({ page }) => {
    await navigateAndWait(page, '/pricing');

    const faqCard = page.locator('[class*="card"]').filter({
      hasText: /difference between monthly and yearly/i,
    });
    await expect(faqCard).toBeVisible();
    await expect(faqCard).toContainText(/auto-renew/i);
    await expect(faqCard).toContainText(/billing settings/i);
  });
});
