import { test, expect } from './helpers/fixtures';
import { TEST_USER, useDistinctClientIp, waitForPageReady } from './helpers/e2e-utils';

test('authentication rate limits resist forged headers while E2E identities stay isolated', async ({
  page,
  context,
}) => {
  await useDistinctClientIp(page);
  await page.goto('/login');
  const statuses = await page.evaluate(async () => {
    const responses: number[] = [];
    for (let index = 1; index <= 6; index += 1) {
      const response = await fetch('/api/auth/kan-144-rate-limit-probe', {
        headers: { 'x-forwarded-for': `192.0.2.${index}`, 'x-real-ip': `198.51.100.${index}` },
      });
      responses.push(response.status);
    }
    return responses;
  });
  expect(statuses).toEqual([401, 401, 401, 401, 401, 429]);

  const otherPage = await context.newPage();
  try {
    await useDistinctClientIp(otherPage);
    await otherPage.goto('/login');
    expect(
      await otherPage.evaluate(
        async () => (await fetch('/api/auth/kan-144-rate-limit-probe')).status
      )
    ).toBe(401);
  } finally {
    await otherPage.close();
  }
});

test.describe('Authentication Flow', () => {
  test.describe('Login Page', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/login');
      await waitForPageReady(page);
    });

    test('should display login form with all required elements', async ({ page }) => {
      // Page heading
      await expect(page.getByText('Welcome back')).toBeVisible();
      await expect(page.getByText('Sign in to your account to continue')).toBeVisible();

      // Form fields
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/^password$/i)).toBeVisible();

      // Submit button
      await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();

      // Forgot password link
      await expect(page.getByRole('link', { name: /forgot password/i })).toBeVisible();

      // Sign up link
      await expect(page.getByRole('link', { name: /sign up/i })).toBeVisible();
    });

    test('should display OAuth separator text', async ({ page }) => {
      await expect(page.getByText(/or continue with email/i)).toBeVisible();
    });

    test('should show validation error for invalid email', async ({ page }) => {
      await page.getByLabel(/email/i).fill('invalid-email');
      await page.getByLabel(/^password$/i).fill('ValidPass123');
      await page.getByRole('button', { name: /sign in/i }).click();

      await expect(page.getByText(/valid email/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should show validation error for short password', async ({ page }) => {
      await page.getByLabel(/email/i).fill('test@example.com');
      await page.getByLabel(/^password$/i).fill('12345');
      await page.getByRole('button', { name: /sign in/i }).click();

      await expect(page.getByText(/at least 6 characters/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should show loading state during submission', async ({ page }) => {
      await page.getByLabel(/email/i).fill(TEST_USER.email);
      await page.getByLabel(/^password$/i).fill(TEST_USER.password);

      // Intercept the Firebase auth call to delay it
      await page.route('**/identitytoolkit.googleapis.com/**', async (route) => {
        await new Promise((r) => setTimeout(r, 1000));
        await route.abort();
      });

      // Click and immediately check for loading state
      // The label changes to "Signing in..." while loading, so match both labels.
      const submitButton = page.getByRole('button', { name: /sign in|signing in/i });
      await submitButton.click();

      // Button should show loading state - check for disabled state and text change
      await expect(submitButton).toBeDisabled({ timeout: 1_000 });
      await expect(page.getByText('Signing in...')).toBeVisible({ timeout: 1_000 });
    });

    test('should navigate to signup page from login', async ({ page }) => {
      await page.getByRole('link', { name: /sign up/i }).click();
      await expect(page).toHaveURL(/\/signup/);
    });

    test('should navigate to forgot password page', async ({ page }) => {
      await Promise.all([
        page.waitForURL(/\/reset-password/),
        page.getByRole('link', { name: /forgot password/i }).click(),
      ]);
      await expect(page).toHaveURL(/\/reset-password/);
    });
  });

  test.describe('Signup Page', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/signup');
      await waitForPageReady(page);
    });

    test('should display signup form with all required elements', async ({ page }) => {
      await expect(page.getByText('Create an account')).toBeVisible();
      await expect(page.getByText('Enter your information to get started')).toBeVisible();

      // Form fields
      await expect(page.getByLabel(/full name/i)).toBeVisible();
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/^password$/i)).toBeVisible();
      await expect(page.getByLabel(/confirm password/i)).toBeVisible();

      // Submit button
      await expect(page.getByRole('button', { name: /create account/i })).toBeVisible();

      // Sign in link
      await expect(page.getByRole('link', { name: /sign in/i })).toBeVisible();
    });

    test('should show selected plan badge when plan query param is present', async ({ page }) => {
      await page.goto('/signup?plan=pro');
      await waitForPageReady(page);

      await expect(page.getByText(/selected plan.*pro/i)).toBeVisible();
    });

    test('should show validation error for short name', async ({ page }) => {
      await page.getByLabel(/full name/i).fill('A');
      await page.getByLabel(/email/i).fill('test@example.com');
      await page.getByLabel(/^password$/i).fill('ValidPass1');
      await page.getByLabel(/confirm password/i).fill('ValidPass1');
      await page.getByRole('button', { name: /create account/i }).click();

      await expect(page.getByText(/at least 2 characters/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should show validation error for weak password', async ({ page }) => {
      await page.getByLabel(/full name/i).fill('Test User');
      await page.getByLabel(/email/i).fill('test@example.com');
      await page.getByLabel(/^password$/i).fill('weakpas');
      await page.getByLabel(/confirm password/i).fill('weakpas');
      await page.getByRole('button', { name: /create account/i }).click();

      await expect(page.getByText(/at least 8 characters/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should show validation error for password mismatch', async ({ page }) => {
      await page.getByLabel(/full name/i).fill('Test User');
      await page.getByLabel(/email/i).fill('test@example.com');
      await page.getByLabel(/^password$/i).fill('ValidPass123');
      await page.getByLabel(/confirm password/i).fill('DifferentPass123');
      await page.getByRole('button', { name: /create account/i }).click();

      await expect(page.getByText(/don't match/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should show password strength requirements', async ({ page }) => {
      await page.getByLabel(/full name/i).fill('Test User');
      await page.getByLabel(/email/i).fill('test@example.com');
      await page.getByLabel(/^password$/i).fill('alllowercase');
      await page.getByLabel(/confirm password/i).fill('alllowercase');
      await page.getByRole('button', { name: /create account/i }).click();

      await expect(page.getByText(/uppercase.*lowercase.*number/i)).toBeVisible({ timeout: 5_000 });
    });

    test('should navigate to login page from signup', async ({ page }) => {
      await page.getByRole('link', { name: /sign in/i }).click();
      await expect(page).toHaveURL(/\/login/);
    });
  });

  test.describe('Password Reset Page', () => {
    test('should load the password reset page', async ({ page }) => {
      await page.goto('/reset-password');
      await waitForPageReady(page);
      await expect(page).toHaveURL(/\/reset-password/);
    });
  });

  test.describe('Email Verification Page', () => {
    test('should load the verify email page', async ({ page }) => {
      // Verify email page redirects unauthenticated users to login
      await page.goto('/verify-email');
      await waitForPageReady(page);
      // Should redirect to login since we're not authenticated
      await expect(page).toHaveURL(/\/login/);
    });
  });

  test.describe('Auth Layout', () => {
    test('should center the auth card on the page', async ({ page }) => {
      await page.goto('/login');
      await waitForPageReady(page);

      const container = page.locator('.min-h-screen.flex.items-center.justify-center');
      await expect(container).toBeVisible();
    });

    test('should have responsive width constraint', async ({ page }) => {
      await page.goto('/login');
      await waitForPageReady(page);

      const wrapper = page.locator('.max-w-md');
      await expect(wrapper).toBeVisible();
    });
  });

  test.describe('Protected Route Redirects', () => {
    test('should redirect /dashboard to /login when not authenticated', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /admin to /login when not authenticated', async ({ page }) => {
      await page.goto('/admin');
      await page.waitForURL(/\/login|\/dashboard/, { timeout: 10_000 });
    });

    test('should redirect /dashboard/profile to /login when not authenticated', async ({
      page,
    }) => {
      await page.goto('/dashboard/profile');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/settings to /login when not authenticated', async ({
      page,
    }) => {
      await page.goto('/dashboard/settings');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/security to /login when not authenticated', async ({
      page,
    }) => {
      await page.goto('/dashboard/security');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });
  });
});
