import { type Page, type BrowserContext, expect } from '@playwright/test';

/**
 * Test credentials for E2E tests.
 * These should match seeded test users in the test database.
 */
export const TEST_USER = {
  email: process.env.TEST_USER_EMAIL || 'testuser@example.com',
  password: process.env.TEST_USER_PASSWORD || 'TestPass123!',
  name: 'Test User',
};

export const TEST_ADMIN = {
  email: process.env.TEST_ADMIN_EMAIL || 'admin@example.com',
  password: process.env.TEST_ADMIN_PASSWORD || 'AdminPass123!',
  name: 'Admin User',
};

/**
 * Log in a user via the login form UI.
 * Use this when testing the actual login flow.
 */
export async function loginViaUI(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');

  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/^password$/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();

  // Wait for navigation to dashboard
  await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
}

/**
 * Set a mock session cookie for authenticated tests.
 * This bypasses the Firebase auth flow for faster, more reliable tests.
 */
export async function setSessionCookie(
  context: BrowserContext,
  sessionValue = 'test-session-cookie'
): Promise<void> {
  await context.addCookies([
    {
      name: 'session',
      value: sessionValue,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ]);
}

/**
 * Assert that the page redirects unauthenticated users to login.
 */
export async function expectRedirectToLogin(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForURL(/\/login/, { timeout: 10_000 });
  await expect(page).toHaveURL(/\/login/);
}

/**
 * Assert that a toast notification appears with the expected text.
 */
export async function expectToast(page: Page, text: string | RegExp): Promise<void> {
  const toast = page.locator(
    '[data-sonner-toast], [role="status"], [data-radix-toast-viewport] li'
  );
  await expect(toast.filter({ hasText: text }).first()).toBeVisible({ timeout: 5_000 });
}

/**
 * Wait for page to be fully loaded (no network activity + DOM stable).
 */
export async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await page.waitForLoadState('domcontentloaded');
}

/**
 * Check that a card metric displays a specific value pattern.
 */
export async function expectMetricCard(
  page: Page,
  title: string | RegExp,
  valuePattern?: string | RegExp
): Promise<void> {
  const card = page.locator('[class*="card"]').filter({ hasText: title });
  await expect(card.first()).toBeVisible();
  if (valuePattern) {
    await expect(card.first()).toContainText(valuePattern);
  }
}

/**
 * Navigate to a page and wait for it to be ready.
 */
export async function navigateAndWait(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await waitForPageReady(page);
}

/**
 * Stripe test card numbers for testing payment flows.
 * @see https://stripe.com/docs/testing#cards
 */
export const STRIPE_TEST_CARDS = {
  success: '4242424242424242',
  requiresAuth: '4000002500003155',
  declined: '4000000000000002',
  insufficientFunds: '4000000000009995',
  expired: '4000000000000069',
  processingError: '4000000000000119',
} as const;

/**
 * Default test billing details for Stripe checkout.
 */
export const TEST_BILLING_DETAILS = {
  email: 'test@example.com',
  cardNumber: STRIPE_TEST_CARDS.success,
  expiry: '12/34',
  cvc: '123',
  zip: '12345',
  name: 'Test User',
  country: 'US',
} as const;

/**
 * Fill Stripe checkout form with test card details.
 * Handles the iframe structure of Stripe's checkout page.
 */
export async function fillStripeCheckout(
  checkoutPage: Page,
  cardNumber: string = STRIPE_TEST_CARDS.success,
  billingDetails = TEST_BILLING_DETAILS
): Promise<void> {
  // Wait for email field
  const emailField = checkoutPage.locator('input[type="email"]').first();
  await emailField.waitFor({ state: 'visible', timeout: 10000 });

  // Fill email if not pre-filled
  const emailValue = await emailField.inputValue();
  if (!emailValue) {
    await emailField.fill(billingDetails.email);
  }

  // Fill card details in iframe
  const cardFrame = checkoutPage.frameLocator('iframe[name*="card"]').first();
  await cardFrame.locator('input[name="number"]').fill(cardNumber);
  await cardFrame.locator('input[name="expiry"]').fill(billingDetails.expiry);
  await cardFrame.locator('input[name="cvc"]').fill(billingDetails.cvc);

  // Fill billing name
  const nameField = checkoutPage.locator('input[name="billingName"]');
  if (await nameField.isVisible().catch(() => false)) {
    await nameField.fill(billingDetails.name);
  }

  // Fill zip code if visible
  const zipField = checkoutPage.locator('input[name="zip"]');
  if (await zipField.isVisible().catch(() => false)) {
    await zipField.fill(billingDetails.zip);
  }
}

/**
 * Submit Stripe checkout payment form.
 */
export async function submitStripeCheckout(checkoutPage: Page): Promise<void> {
  const submitButton = checkoutPage.getByRole('button', { name: /pay|subscribe/i });
  await submitButton.click();
}

/**
 * Wait for subscription success redirect and processing.
 * Returns true if subscription was successfully activated.
 */
export async function waitForSubscriptionSuccess(
  page: Page,
  timeoutMs: number = 40000
): Promise<boolean> {
  try {
    // Wait for redirect to dashboard with success parameter
    await page.waitForURL(/\/dashboard\?upgrade=success/, { timeout: timeoutMs });

    // Should show processing or success message
    await expect(
      page.getByText(/processing your subscription|subscription activated/i)
    ).toBeVisible({ timeout: 10000 });

    // Wait for polling to complete and auto-refresh
    // SubscriptionSuccessHandler polls every 3s for up to 30s, then refreshes
    await page.waitForURL('/dashboard', { timeout: 35000 });

    return true;
  } catch (error) {
    console.error('Failed to wait for subscription success:', error);
    return false;
  }
}

/**
 * Verify subscription tier is displayed correctly on dashboard.
 */
export async function expectSubscriptionTier(
  page: Page,
  tier: 'free' | 'pro' | 'enterprise'
): Promise<void> {
  const subscriptionCard = page.locator('[class*="card"]').filter({
    hasText: /subscription plan/i,
  });
  await expect(subscriptionCard).toContainText(new RegExp(tier, 'i'), { timeout: 10000 });
}

/**
 * Navigate to the billing settings page.
 */
export async function navigateToBilling(page: Page): Promise<void> {
  await navigateAndWait(page, '/dashboard/settings/billing');
  await expect(page.getByRole('heading', { name: /billing & subscription/i })).toBeVisible({
    timeout: 10_000,
  });
}

/**
 * Toggle auto-renewal on the billing page and wait for the action to complete.
 */
export async function toggleAutoRenewal(page: Page): Promise<void> {
  const renewalCard = page.locator('[class*="card"]').filter({ hasText: /auto-renewal/i });
  const toggle = renewalCard.locator('button[role="switch"]');
  await toggle.click();
  // Wait for toast confirmation
  await expect(
    page.getByText(/auto-renewal turned|subscription will renew|subscription will expire/i)
  ).toBeVisible({ timeout: 10_000 });
}
