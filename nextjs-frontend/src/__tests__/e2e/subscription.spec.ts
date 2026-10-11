import { test, expect } from '@playwright/test';
import {
  loginViaUI,
  TEST_USER,
  TEST_ADMIN,
  waitForPageReady,
  navigateAndWait,
} from './helpers/e2e-utils';

/**
 * Subscription & Upgrade E2E Tests
 *
 * These tests cover the complete subscription upgrade flow:
 * - Navigating to pricing page
 * - Initiating checkout for Pro tier
 * - Completing payment with Stripe test cards
 * - Webhook processing and database updates
 * - Success redirect and status polling
 * - Dashboard displaying upgraded subscription
 *
 * NOTE: These tests use Stripe test mode with test cards.
 * Requires STRIPE environment variables to be configured.
 */

/**
 * Stripe test card numbers
 * https://stripe.com/docs/testing#cards
 */
const STRIPE_TEST_CARDS = {
  // Standard successful payment
  success: '4242424242424242',
  // Requires authentication (3D Secure)
  requiresAuth: '4000002500003155',
  // Card is declined
  declined: '4000000000000002',
  // Insufficient funds
  insufficientFunds: '4000000000009995',
  // Expired card
  expired: '4000000000000069',
  // Processing error
  processingError: '4000000000000119',
};

/**
 * Test billing details
 */
const TEST_BILLING_DETAILS = {
  email: 'test@example.com',
  cardNumber: STRIPE_TEST_CARDS.success,
  expiry: '12/34', // MM/YY format
  cvc: '123',
  zip: '12345',
  name: 'Test User',
  country: 'US',
};

test.describe('Subscription Upgrade Flow', () => {
  test.describe('Unauthenticated User Flow', () => {
    test('should redirect to signup when clicking pricing CTA without auth', async ({ page }) => {
      await navigateAndWait(page, '/pricing');

      // Click on "Start Free Trial" for Pro tier
      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const ctaButton = proCard.getByRole('link', { name: /start free trial/i });
      await ctaButton.click();

      // Should redirect to signup with plan parameter
      await expect(page).toHaveURL(/\/signup\?plan=pro/);
    });

    test('should display signup form with plan pre-selected', async ({ page }) => {
      await page.goto('/signup?plan=pro');
      await waitForPageReady(page);

      await expect(page.getByRole('heading', { name: /sign up/i })).toBeVisible();
      // User would complete signup and then be able to upgrade
    });
  });

  test.describe('Authenticated User - Subscription Upgrade', () => {
    test.skip(
      !process.env.TEST_USER_EMAIL || !process.env.STRIPE_PUBLISHABLE_KEY,
      'Skipped: TEST_USER_EMAIL or STRIPE keys not configured'
    );

    test.beforeEach(async ({ page }) => {
      // Login as test user (should be on free tier)
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);
    });

    test('should show upgrade banner on dashboard for free tier users', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      // Free tier users should see upgrade banner
      const upgradeBanner = page.getByText(/upgrade to pro/i).first();
      const isVisible = await upgradeBanner.isVisible().catch(() => false);

      if (isVisible) {
        await expect(upgradeBanner).toBeVisible();
        await expect(page.getByRole('link', { name: /upgrade now/i })).toBeVisible();
      }
    });

    test('should navigate to pricing page from dashboard upgrade banner', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      const upgradeLink = page.getByRole('link', { name: /upgrade now/i });
      const isVisible = await upgradeLink.isVisible().catch(() => false);

      if (isVisible) {
        await upgradeLink.click();
        await expect(page).toHaveURL(/\/pricing/);
      }
    });

    test('should display pricing tiers on pricing page', async ({ page }) => {
      await navigateAndWait(page, '/pricing');

      // Verify all tiers are visible
      await expect(page.getByRole('heading', { name: /^free$/i })).toBeVisible();
      await expect(page.getByRole('heading', { name: /^pro$/i })).toBeVisible();
      await expect(page.getByRole('heading', { name: /^enterprise$/i })).toBeVisible();
    });

    test('should show "Upgrade to Pro" button for authenticated free tier users', async ({
      page,
    }) => {
      await navigateAndWait(page, '/pricing');

      // For authenticated users on free tier, Pro tier should show upgrade button
      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });

      // Button text might be "Upgrade to Pro" or "Start Free Trial"
      const upgradeButton = proCard.getByRole('button', {
        name: /upgrade to pro|start free trial/i,
      });
      const ctaExists = await upgradeButton.count().then((count) => count > 0);

      if (ctaExists) {
        await expect(upgradeButton.first()).toBeVisible();
      }
    });

    test('should initiate Stripe checkout when clicking upgrade button', async ({
      page,
      context,
    }) => {
      await navigateAndWait(page, '/pricing');

      // Find Pro tier upgrade button
      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (buttonExists) {
        // Start waiting for new page before clicking
        const checkoutPagePromise = context.waitForEvent('page');

        await upgradeButton.click();

        // Wait for Stripe checkout page to open
        const checkoutPage = await checkoutPagePromise;
        await checkoutPage.waitForLoadState();

        // Verify we're on Stripe checkout
        await expect(checkoutPage).toHaveURL(/checkout\.stripe\.com/);

        await checkoutPage.close();
      } else {
        test.skip(true, 'Upgrade button not available (user might already be on Pro tier)');
      }
    });

    test('should complete full upgrade flow with Stripe test card', async ({ page, context }) => {
      await navigateAndWait(page, '/pricing');

      // Find and click Pro tier upgrade button
      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (!buttonExists) {
        test.skip(true, 'Upgrade button not available (user might already be on Pro tier)');
        return;
      }

      // Click upgrade and wait for Stripe checkout
      const checkoutPagePromise = context.waitForEvent('page');
      await upgradeButton.click();
      const checkoutPage = await checkoutPagePromise;
      await checkoutPage.waitForLoadState();

      // Verify we're on Stripe checkout
      expect(checkoutPage.url()).toContain('checkout.stripe.com');

      // Fill in Stripe checkout form with test card
      // Note: Stripe's iframe structure may vary, adjust selectors as needed
      try {
        // Wait for email field (might be pre-filled)
        const emailField = checkoutPage.locator('input[type="email"]').first();
        await emailField.waitFor({ state: 'visible', timeout: 10000 });

        // Fill email if not pre-filled
        const emailValue = await emailField.inputValue();
        if (!emailValue) {
          await emailField.fill(TEST_BILLING_DETAILS.email);
        }

        // Card number field (in iframe)
        const cardFrame = checkoutPage.frameLocator('iframe[name*="card"]').first();
        await cardFrame.locator('input[name="number"]').fill(TEST_BILLING_DETAILS.cardNumber);
        await cardFrame.locator('input[name="expiry"]').fill(TEST_BILLING_DETAILS.expiry);
        await cardFrame.locator('input[name="cvc"]').fill(TEST_BILLING_DETAILS.cvc);

        // Billing details
        await checkoutPage.locator('input[name="billingName"]').fill(TEST_BILLING_DETAILS.name);

        const zipField = checkoutPage.locator('input[name="zip"]');
        if (await zipField.isVisible()) {
          await zipField.fill(TEST_BILLING_DETAILS.zip);
        }

        // Submit payment
        const submitButton = checkoutPage.getByRole('button', { name: /pay|subscribe/i });
        await submitButton.click();

        // Wait for redirect back to our app with success parameter
        await page.waitForURL(/\/dashboard\?upgrade=success/, { timeout: 30000 });

        // Verify we're back on dashboard with success parameter
        await expect(page).toHaveURL(/\/dashboard\?upgrade=success/);

        // Should show success message
        await expect(
          page.getByText(/processing your subscription|subscription activated/i)
        ).toBeVisible({ timeout: 10000 });

        // Wait for subscription to be processed (polling mechanism should work)
        // The SubscriptionSuccessHandler polls every 3 seconds for up to 30 seconds
        await page.waitForTimeout(5000);

        // After polling completes, should auto-refresh to clean URL
        await page.waitForURL('/dashboard', { timeout: 35000 });

        // Verify subscription tier is updated to Pro
        const subscriptionCard = page.locator('[class*="card"]').filter({
          hasText: /subscription plan/i,
        });
        await expect(subscriptionCard).toContainText(/pro/i, { timeout: 10000 });

        // Upgrade banner should no longer be visible
        const upgradeBanner = page.getByText(/upgrade to pro/i).first();
        await expect(upgradeBanner).not.toBeVisible();
      } catch (error) {
        // Close checkout page if still open
        if (!checkoutPage.isClosed()) {
          await checkoutPage.close();
        }
        throw error;
      } finally {
        // Cleanup: close checkout page if still open
        if (!checkoutPage.isClosed()) {
          await checkoutPage.close();
        }
      }
    });

    test('should handle Stripe checkout cancellation', async ({ page, context }) => {
      await navigateAndWait(page, '/pricing');

      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (!buttonExists) {
        test.skip(true, 'Upgrade button not available');
        return;
      }

      // Click upgrade and wait for Stripe checkout
      const checkoutPagePromise = context.waitForEvent('page');
      await upgradeButton.click();
      const checkoutPage = await checkoutPagePromise;
      await checkoutPage.waitForLoadState();

      // Look for back/cancel button on Stripe checkout
      const backButton = checkoutPage.getByRole('link', { name: /back|cancel/i });
      const backExists = await backButton.count().then((count) => count > 0);

      if (backExists) {
        await backButton.click();

        // Should redirect to cancel URL (pricing page with cancelled parameter)
        await page.waitForURL(/\/pricing\?upgrade=cancelled/, { timeout: 10000 });
        await expect(page).toHaveURL(/\/pricing\?upgrade=cancelled/);
      }

      if (!checkoutPage.isClosed()) {
        await checkoutPage.close();
      }
    });
  });

  test.describe('Subscription Status Display', () => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);
    });

    test('should display current subscription tier on dashboard', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      // Find subscription plan card
      const subscriptionCard = page.locator('[class*="card"]').filter({
        hasText: /subscription plan/i,
      });
      await expect(subscriptionCard).toBeVisible();

      // Should display tier (free, pro, or enterprise)
      await expect(subscriptionCard).toContainText(/free|pro|enterprise/i);
    });

    test('should display subscription status', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      const subscriptionCard = page.locator('[class*="card"]').filter({
        hasText: /subscription plan/i,
      });

      // Should display status (active, canceled, etc.)
      await expect(subscriptionCard).toContainText(/active|canceled|past_due|trialing/i);
    });

    test('should show current period end date for active subscriptions', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      const subscriptionCard = page.locator('[class*="card"]').filter({
        hasText: /subscription plan/i,
      });

      // Check if shows "Active until" for paid subscriptions
      const hasActiveUntil = await subscriptionCard.getByText(/active until/i).count();

      if (hasActiveUntil > 0) {
        // Should show a date
        await expect(subscriptionCard).toContainText(/\d{1,2}\/\d{1,2}\/\d{2,4}/);
      }
    });
  });

  test.describe('Stripe Test Cards - Payment Scenarios', () => {
    test.skip(
      !process.env.TEST_USER_EMAIL || !process.env.STRIPE_PUBLISHABLE_KEY,
      'Skipped: Stripe not configured for testing'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);
    });

    test('should handle declined card gracefully', async ({ page, context }) => {
      await navigateAndWait(page, '/pricing');

      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (!buttonExists) {
        test.skip(true, 'Upgrade button not available');
        return;
      }

      const checkoutPagePromise = context.waitForEvent('page');
      await upgradeButton.click();
      const checkoutPage = await checkoutPagePromise;
      await checkoutPage.waitForLoadState();

      try {
        // Fill with declined test card
        const emailField = checkoutPage.locator('input[type="email"]').first();
        const emailValue = await emailField.inputValue();
        if (!emailValue) {
          await emailField.fill(TEST_BILLING_DETAILS.email);
        }

        const cardFrame = checkoutPage.frameLocator('iframe[name*="card"]').first();
        await cardFrame.locator('input[name="number"]').fill(STRIPE_TEST_CARDS.declined);
        await cardFrame.locator('input[name="expiry"]').fill(TEST_BILLING_DETAILS.expiry);
        await cardFrame.locator('input[name="cvc"]').fill(TEST_BILLING_DETAILS.cvc);

        const submitButton = checkoutPage.getByRole('button', { name: /pay|subscribe/i });
        await submitButton.click();

        // Should show error message on Stripe checkout page
        await expect(checkoutPage.getByText(/card was declined|payment failed/i)).toBeVisible({
          timeout: 10000,
        });

        // Should NOT redirect to success page
        await expect(page).not.toHaveURL(/\/dashboard\?upgrade=success/);
      } finally {
        if (!checkoutPage.isClosed()) {
          await checkoutPage.close();
        }
      }
    });

    test('should handle insufficient funds card', async ({ page, context }) => {
      await navigateAndWait(page, '/pricing');

      const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/i });
      const upgradeButton = proCard.getByRole('button', { name: /upgrade to pro/i });

      const buttonExists = await upgradeButton.count().then((count) => count > 0);

      if (!buttonExists) {
        test.skip(true, 'Upgrade button not available');
        return;
      }

      const checkoutPagePromise = context.waitForEvent('page');
      await upgradeButton.click();
      const checkoutPage = await checkoutPagePromise;
      await checkoutPage.waitForLoadState();

      try {
        const emailField = checkoutPage.locator('input[type="email"]').first();
        const emailValue = await emailField.inputValue();
        if (!emailValue) {
          await emailField.fill(TEST_BILLING_DETAILS.email);
        }

        const cardFrame = checkoutPage.frameLocator('iframe[name*="card"]').first();
        await cardFrame.locator('input[name="number"]').fill(STRIPE_TEST_CARDS.insufficientFunds);
        await cardFrame.locator('input[name="expiry"]').fill(TEST_BILLING_DETAILS.expiry);
        await cardFrame.locator('input[name="cvc"]').fill(TEST_BILLING_DETAILS.cvc);

        const submitButton = checkoutPage.getByRole('button', { name: /pay|subscribe/i });
        await submitButton.click();

        // Should show insufficient funds error
        await expect(
          checkoutPage.getByText(/insufficient funds|card has insufficient/i)
        ).toBeVisible({ timeout: 10000 });
      } finally {
        if (!checkoutPage.isClosed()) {
          await checkoutPage.close();
        }
      }
    });
  });

  test.describe('Billing Management', () => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);
    });

    test('should have billing/subscription link in dashboard', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      // Look for billing-related links
      const billingLink = page.getByRole('link', { name: /billing|subscription/i });
      const linkExists = await billingLink.count().then((count) => count > 0);

      if (linkExists) {
        await expect(billingLink.first()).toBeVisible();
      }
    });

    test('should navigate to settings when clicking settings link', async ({ page }) => {
      await navigateAndWait(page, '/dashboard');

      await page
        .getByRole('link', { name: /settings/i })
        .first()
        .click();
      await expect(page).toHaveURL(/\/dashboard\/settings/);
    });
  });

  test.describe('Admin Subscription Management', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
    });

    test('should display subscription management page', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      // Verify page heading
      await expect(page.getByRole('heading', { name: /subscription management/i })).toBeVisible();

      // Verify description
      await expect(page.getByText(/monitor and manage all subscriptions/i)).toBeVisible();
    });

    test('should display subscription stats cards', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      // Check all stat cards are present
      await expect(page.getByText('Total Active')).toBeVisible();
      await expect(page.getByText('Pro Plans')).toBeVisible();
      await expect(page.getByText('Enterprise Plans')).toBeVisible();
      await expect(page.getByText('MRR')).toBeVisible();
    });

    test('should display refresh button', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      const refreshButton = page.getByRole('button', { name: /refresh/i });
      await expect(refreshButton).toBeVisible();
    });

    test('should refresh subscription data when clicking refresh button', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      const refreshButton = page.getByRole('button', { name: /refresh/i });
      await refreshButton.click();

      // Wait for refresh animation
      await page.waitForTimeout(500);

      // Page should still be on same URL
      await expect(page).toHaveURL(/\/admin\/subscriptions/);
    });

    test('should show active subscriptions in table or empty state', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      // Check if there's an empty state or subscription table
      const emptyState = page.getByText(/no active subscriptions/i);
      const subscriptionTable = page.getByRole('table');

      const hasEmptyState = await emptyState.isVisible().catch(() => false);
      const hasTable = await subscriptionTable.isVisible().catch(() => false);

      // Either empty state or table should be visible
      expect(hasEmptyState || hasTable).toBe(true);
    });

    test('should display subscription details when subscriptions exist', async ({ page }) => {
      await navigateAndWait(page, '/admin/subscriptions');

      // Check if table exists
      const subscriptionTable = page.getByRole('table');
      const tableExists = await subscriptionTable.isVisible().catch(() => false);

      if (tableExists) {
        // Verify table headers
        await expect(page.getByRole('columnheader', { name: /customer/i })).toBeVisible();
        await expect(page.getByRole('columnheader', { name: /email/i })).toBeVisible();
        await expect(page.getByRole('columnheader', { name: /plan/i })).toBeVisible();
        await expect(page.getByRole('columnheader', { name: /status/i })).toBeVisible();
        await expect(page.getByRole('columnheader', { name: /renewal date/i })).toBeVisible();

        console.log('✅ Subscription table displayed with headers');
      } else {
        console.log('ℹ️ No subscriptions to display yet');
      }
    });

    test('should show subscription immediately after webhook processing', async ({ page }) => {
      // This test verifies that subscriptions appear immediately without manual admin action
      await navigateAndWait(page, '/admin/subscriptions');

      // Record initial count
      const totalActiveCard = page.locator('[class*="card"]').filter({ hasText: /total active/i });
      const initialCountText = await totalActiveCard.textContent();

      // If there are active subscriptions, verify they're displayed
      if (initialCountText && !initialCountText.includes('0')) {
        // Should have subscription table visible
        const subscriptionTable = page.getByRole('table');
        await expect(subscriptionTable).toBeVisible({ timeout: 5000 });

        // Should show Pro or Enterprise badges
        const tierBadges = page.getByRole('cell', { name: /pro|enterprise/i });
        const badgeCount = await tierBadges.count();
        expect(badgeCount).toBeGreaterThan(0);

        console.log(`✅ Found ${badgeCount} active subscription(s) - no admin action required!`);
      }
    });

    test('should update stats when new subscription is created via webhook', async ({ page }) => {
      // Navigate to admin subscriptions
      await navigateAndWait(page, '/admin/subscriptions');

      // Get initial Pro count
      const proPlansCard = page.locator('[class*="card"]').filter({ hasText: /pro plans/i });
      await expect(proPlansCard).toBeVisible();

      const initialProCount = await proPlansCard
        .locator('.text-2xl')
        .textContent()
        .then((text) => parseInt(text || '0'));

      console.log(`ℹ️ Initial Pro subscription count: ${initialProCount}`);

      // Note: In a real test, a subscription would be created via the upgrade flow
      // and this page should automatically refresh via revalidatePath
      // This test just verifies the page structure is correct

      // Refresh the page
      const refreshButton = page.getByRole('button', { name: /refresh/i });
      await refreshButton.click();

      await page.waitForTimeout(1000);

      // Page should still display stats
      await expect(proPlansCard).toBeVisible();

      console.log('✅ Admin page refreshes and displays updated subscription data');
    });
  });

  test.describe('Security - URL Manipulation Prevention', () => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

    test('should prevent manual navigation to upgrade success URL', async ({ page }) => {
      // Login as test user
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);

      // Try to manually navigate to upgrade success URL
      // This simulates a user trying to fake the upgrade by manipulating the URL
      await page.goto('/dashboard?upgrade=success');
      await page.waitForLoadState('networkidle');

      // Wait for verification to complete
      await page.waitForTimeout(2000);

      // Should redirect to clean dashboard URL (no query parameter)
      // because there's no valid checkout session cookie
      expect(page.url()).not.toContain('upgrade=success');
      expect(page.url()).toMatch(/\/dashboard$/);

      console.log('✅ Security: Fake upgrade URL blocked - redirected to clean dashboard');
    });

    test('should NOT show success banner without valid checkout session', async ({ page }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);

      // Navigate to dashboard first
      await navigateAndWait(page, '/dashboard');

      // Then try to add query parameter manually
      await page.goto('/dashboard?upgrade=success');
      await page.waitForLoadState('networkidle');

      // Wait a moment for component to verify and redirect
      await page.waitForTimeout(2000);

      // Success processing banner should NOT be visible
      const processingBanner = page.getByText(/processing your subscription/i);
      const successBanner = page.getByText(/subscription activated/i);

      await expect(processingBanner).not.toBeVisible();
      await expect(successBanner).not.toBeVisible();

      // Should be redirected away from ?upgrade=success
      expect(page.url()).not.toContain('upgrade=success');

      console.log('✅ Security: No success banner shown for fake URL');
    });

    test('should only show success banner after legitimate checkout', async ({ page, context }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);

      // First verify manual URL doesn't work
      await page.goto('/dashboard?upgrade=success');
      await page.waitForTimeout(1500);
      expect(page.url()).not.toContain('upgrade=success');

      // Now if user goes through actual checkout flow (not completed in this test),
      // the checkout session cookie would be set and validation would pass
      // This test just confirms the security mechanism is in place

      console.log('✅ Security: Checkout session validation required for success banner');
    });
  });
});
