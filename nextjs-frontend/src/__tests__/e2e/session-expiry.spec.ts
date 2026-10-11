import { test, expect } from '@playwright/test';
import { setSessionCookie, waitForPageReady } from './helpers/e2e-utils';

/**
 * Session Expiry E2E Tests
 *
 * Verifies that users with expired/invalid session cookies
 * are properly redirected to the login page.
 * These tests do NOT require Firebase credentials.
 */

test.describe('Session Expiry Redirect', () => {
  test.describe('Invalid session cookie', () => {
    test('should redirect /dashboard to /login with invalid session', async ({ page, context }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 15_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/profile to /login with invalid session', async ({
      page,
      context,
    }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard/profile');
      await page.waitForURL(/\/login/, { timeout: 15_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/settings to /login with invalid session', async ({
      page,
      context,
    }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard/settings');
      await page.waitForURL(/\/login/, { timeout: 15_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/security to /login with invalid session', async ({
      page,
      context,
    }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard/security');
      await page.waitForURL(/\/login/, { timeout: 15_000 });
      await expect(page).toHaveURL(/\/login/);
    });
  });

  test.describe('Session cookie cleanup', () => {
    test('should clear the session cookie after redirect', async ({ page, context }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 15_000 });

      // After redirect, the session cookie should be deleted
      const cookies = await context.cookies();
      const sessionCookie = cookies.find((c) => c.name === 'session');
      expect(sessionCookie).toBeUndefined();
    });

    test('should clear the email-verified cookie after redirect', async ({ page, context }) => {
      // Set both cookies
      await setSessionCookie(context, 'invalid-expired-token');
      await context.addCookies([
        {
          name: 'email-verified',
          value: 'true',
          domain: 'localhost',
          path: '/',
          httpOnly: false,
          secure: false,
          sameSite: 'Lax',
        },
      ]);

      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 15_000 });

      // Both cookies should be cleared
      const cookies = await context.cookies();
      const emailCookie = cookies.find((c) => c.name === 'email-verified');
      expect(emailCookie).toBeUndefined();
    });
  });

  test.describe('No session cookie', () => {
    test('should redirect /dashboard to /login without any session', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect /dashboard/profile to /login without any session', async ({ page }) => {
      await page.goto('/dashboard/profile');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });
  });

  test.describe('Login page after redirect', () => {
    test('should display login form after session expiry redirect', async ({ page, context }) => {
      await setSessionCookie(context, 'invalid-expired-token');
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 15_000 });
      await waitForPageReady(page);

      // Login form should be visible
      await expect(page.getByLabel(/email/i)).toBeVisible();
      await expect(page.getByLabel(/password/i)).toBeVisible();
      await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
    });
  });
});
