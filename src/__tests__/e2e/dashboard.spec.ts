import { test, expect } from '@playwright/test';
import { loginViaUI, TEST_USER, waitForPageReady } from './helpers/e2e-utils';

/**
 * Customer Dashboard E2E Tests
 *
 * These tests cover the customer-facing dashboard pages including:
 * - Dashboard home (stats, quick actions, account info, activity)
 * - Profile management (view/edit profile, avatar upload)
 * - Settings (theme, notifications, language, timezone)
 * - Security (password change, 2FA, login history, data export, account deletion)
 *
 * NOTE: Tests that require authentication will attempt to log in via UI.
 * If Firebase is not configured for test env, these tests will be skipped.
 * For CI, use seeded test users with known credentials.
 */

test.describe('Customer Dashboard', () => {
  test.describe('Dashboard Home Page', () => {
    test('should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/dashboard');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test.describe('When authenticated', () => {
      test.skip(
        !process.env.TEST_USER_EMAIL,
        'Skipped: TEST_USER_EMAIL not configured'
      );

      test.beforeEach(async ({ page }) => {
        await loginViaUI(page, TEST_USER.email, TEST_USER.password);
      });

      test('should display dashboard heading and welcome message', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /dashboard/i })).toBeVisible();
        await expect(page.getByText(/welcome back/i)).toBeVisible();
      });

      test('should display stats grid with 4 metric cards', async ({ page }) => {
        // Account Status card
        await expect(page.getByText('Account Status')).toBeVisible();

        // Subscription Plan card
        await expect(page.getByText('Subscription Plan')).toBeVisible();

        // Notifications card
        await expect(page.getByText(/^notifications$/i)).toBeVisible();

        // Total Logins card
        await expect(page.getByText('Total Logins')).toBeVisible();
      });

      test('should display quick action cards', async ({ page }) => {
        await expect(page.getByText('Quick Actions')).toBeVisible();

        // Quick action links
        await expect(page.getByRole('link', { name: /edit profile/i })).toBeVisible();
        await expect(page.getByRole('link', { name: /settings/i })).toBeVisible();
        await expect(page.getByRole('link', { name: /security/i })).toBeVisible();
        await expect(page.getByRole('link', { name: /billing/i })).toBeVisible();
      });

      test('should display account information section', async ({ page }) => {
        await expect(page.getByText('Account Information')).toBeVisible();
        await expect(page.getByText(/email/i)).toBeVisible();
        await expect(page.getByText(/member since/i)).toBeVisible();
        await expect(page.getByText(/last login/i)).toBeVisible();
      });

      test('should display recent activity section', async ({ page }) => {
        await expect(page.getByText('Recent Activity')).toBeVisible();
      });

      test('should display account summary section', async ({ page }) => {
        await expect(page.getByText('Account Summary')).toBeVisible();
        await expect(page.getByText(/account age/i)).toBeVisible();
        await expect(page.getByText(/current plan/i)).toBeVisible();
      });

      test('should show upgrade banner for free tier users', async ({ page }) => {
        // This depends on the test user being on free tier
        const upgradeBanner = page.getByText(/upgrade to pro/i);
        const isVisible = await upgradeBanner.isVisible().catch(() => false);

        if (isVisible) {
          await expect(page.getByRole('link', { name: /upgrade now/i })).toBeVisible();
        }
      });

      test('should navigate to profile via quick action', async ({ page }) => {
        await page.getByRole('link', { name: /edit profile/i }).click();
        await expect(page).toHaveURL(/\/dashboard\/profile/);
      });

      test('should navigate to settings via quick action', async ({ page }) => {
        await page.getByRole('link', { name: /settings/i }).first().click();
        await expect(page).toHaveURL(/\/dashboard\/settings/);
      });

      test('should navigate to security via quick action', async ({ page }) => {
        await page.getByRole('link', { name: /security/i }).first().click();
        await expect(page).toHaveURL(/\/dashboard\/security/);
      });

      test('should display edit profile button in account info', async ({ page }) => {
        const editProfileBtn = page.getByRole('link', { name: /edit profile/i });
        await expect(editProfileBtn.first()).toBeVisible();
      });
    });
  });

  test.describe('Dashboard Layout & Navigation', () => {
    test.skip(
      !process.env.TEST_USER_EMAIL,
      'Skipped: TEST_USER_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_USER.email, TEST_USER.password);
    });

    test('should display top navigation bar', async ({ page }) => {
      await expect(page.getByRole('link', { name: /dashboard/i }).first()).toBeVisible();
    });

    test('should display navigation links', async ({ page }) => {
      const nav = page.locator('nav');
      await expect(nav).toBeVisible();

      await expect(page.getByRole('link', { name: /^home$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /profile/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /settings/i }).first()).toBeVisible();
      await expect(page.getByRole('link', { name: /security/i }).first()).toBeVisible();
    });

    test('should navigate between dashboard pages', async ({ page }) => {
      // Navigate to Profile
      await page.getByRole('link', { name: /profile/i }).first().click();
      await expect(page).toHaveURL(/\/dashboard\/profile/);

      // Navigate to Settings
      await page.getByRole('link', { name: /settings/i }).first().click();
      await expect(page).toHaveURL(/\/dashboard\/settings/);

      // Navigate to Security
      await page.getByRole('link', { name: /security/i }).first().click();
      await expect(page).toHaveURL(/\/dashboard\/security/);

      // Navigate back to Home
      await page.getByRole('link', { name: /^home$/i }).click();
      await expect(page).toHaveURL(/\/dashboard$/);
    });
  });

  test.describe('Profile Page', () => {
    test('should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/dashboard/profile');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test.describe('When authenticated', () => {
      test.skip(
        !process.env.TEST_USER_EMAIL,
        'Skipped: TEST_USER_EMAIL not configured'
      );

      test.beforeEach(async ({ page }) => {
        await loginViaUI(page, TEST_USER.email, TEST_USER.password);
        await page.goto('/dashboard/profile');
        await waitForPageReady(page);
      });

      test('should display profile page heading', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /profile/i })).toBeVisible();
        await expect(page.getByText(/manage your public profile/i)).toBeVisible();
      });

      test('should display avatar section with upload button', async ({ page }) => {
        await expect(page.getByText('Profile Picture')).toBeVisible();
        await expect(page.getByText(/upload photo/i)).toBeVisible();
      });

      test('should display personal information form', async ({ page }) => {
        await expect(page.getByText('Personal Information')).toBeVisible();

        // Read-only email field
        await expect(page.getByLabel(/email/i).first()).toBeVisible();

        // Editable fields
        await expect(page.getByLabel(/display name/i)).toBeVisible();
        await expect(page.getByLabel(/bio/i)).toBeVisible();
        await expect(page.getByLabel(/location/i)).toBeVisible();
        await expect(page.getByLabel(/website/i)).toBeVisible();
        await expect(page.getByLabel(/phone/i)).toBeVisible();
      });

      test('should have save and cancel buttons', async ({ page }) => {
        await expect(page.getByRole('button', { name: /save changes/i })).toBeVisible();
        await expect(page.getByRole('button', { name: /cancel/i })).toBeVisible();
      });

      test('should show email field as disabled (read-only)', async ({ page }) => {
        const emailInput = page.getByLabel(/email/i).first();
        await expect(emailInput).toBeDisabled();
      });

      test('should validate display name minimum length', async ({ page }) => {
        await page.getByLabel(/display name/i).fill('A');
        await page.getByRole('button', { name: /save changes/i }).click();

        await expect(
          page.getByText(/at least 2 characters/i)
        ).toBeVisible({ timeout: 5_000 });
      });

      test('should validate website URL format', async ({ page }) => {
        await page.getByLabel(/website/i).fill('not-a-url');
        await page.getByRole('button', { name: /save changes/i }).click();

        await expect(page.getByText(/valid url/i)).toBeVisible({ timeout: 5_000 });
      });

      test('should validate bio max length', async ({ page }) => {
        const longBio = 'a'.repeat(501);
        await page.getByLabel(/bio/i).fill(longBio);
        await page.getByRole('button', { name: /save changes/i }).click();

        await expect(
          page.getByText(/500 characters/i)
        ).toBeVisible({ timeout: 5_000 });
      });
    });
  });

  test.describe('Settings Page', () => {
    test('should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/dashboard/settings');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test.describe('When authenticated', () => {
      test.skip(
        !process.env.TEST_USER_EMAIL,
        'Skipped: TEST_USER_EMAIL not configured'
      );

      test.beforeEach(async ({ page }) => {
        await loginViaUI(page, TEST_USER.email, TEST_USER.password);
        await page.goto('/dashboard/settings');
        await waitForPageReady(page);
      });

      test('should display settings page heading', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /settings/i })).toBeVisible();
        await expect(page.getByText(/manage your account preferences/i)).toBeVisible();
      });

      test('should display appearance settings section', async ({ page }) => {
        await expect(page.getByText(/^appearance$/i)).toBeVisible();
        await expect(page.getByText(/customize how the app looks/i)).toBeVisible();
        await expect(page.getByLabel(/theme/i)).toBeVisible();
      });

      test('should display notification settings section', async ({ page }) => {
        await expect(page.getByText(/^notifications$/i).first()).toBeVisible();
        await expect(page.getByText(/email notifications/i)).toBeVisible();
      });

      test('should display regional settings section', async ({ page }) => {
        await expect(page.getByText('Regional Settings')).toBeVisible();
        await expect(page.getByLabel(/language/i)).toBeVisible();
        await expect(page.getByLabel(/timezone/i)).toBeVisible();
      });

      test('should have save and reset buttons', async ({ page }) => {
        await expect(page.getByRole('button', { name: /save settings/i })).toBeVisible();
        await expect(page.getByRole('button', { name: /reset/i })).toBeVisible();
      });

      test('should have email notification toggle switch', async ({ page }) => {
        const toggle = page.locator('[role="switch"]');
        await expect(toggle).toBeVisible();
      });
    });
  });

  test.describe('Security Page', () => {
    test('should redirect to login when not authenticated', async ({ page }) => {
      await page.goto('/dashboard/security');
      await page.waitForURL(/\/login/, { timeout: 10_000 });
      await expect(page).toHaveURL(/\/login/);
    });

    test.describe('When authenticated', () => {
      test.skip(
        !process.env.TEST_USER_EMAIL,
        'Skipped: TEST_USER_EMAIL not configured'
      );

      test.beforeEach(async ({ page }) => {
        await loginViaUI(page, TEST_USER.email, TEST_USER.password);
        await page.goto('/dashboard/security');
        await waitForPageReady(page);
      });

      test('should display security page heading', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /security/i })).toBeVisible();
        await expect(page.getByText(/manage your account security/i)).toBeVisible();
      });

      test('should display password management section', async ({ page }) => {
        await expect(page.getByText(/^password$/i).first()).toBeVisible();
        await expect(page.getByRole('button', { name: /change password/i })).toBeVisible();
      });

      test('should display two-factor authentication section', async ({ page }) => {
        await expect(page.getByText(/two-factor authentication/i).first()).toBeVisible();
        await expect(page.getByText(/2fa status/i)).toBeVisible();

        // Either Enable or Disable button should be visible
        const enableBtn = page.getByRole('button', { name: /enable 2fa/i });
        const disableBtn = page.getByRole('button', { name: /disable 2fa/i });

        const enableVisible = await enableBtn.isVisible().catch(() => false);
        const disableVisible = await disableBtn.isVisible().catch(() => false);
        expect(enableVisible || disableVisible).toBeTruthy();
      });

      test('should display login history section', async ({ page }) => {
        await expect(page.getByText(/login history/i).first()).toBeVisible();
        await expect(page.getByText(/review recent activity/i)).toBeVisible();
      });

      test('should display data export section', async ({ page }) => {
        await expect(page.getByText('Data Export')).toBeVisible();
        await expect(page.getByRole('button', { name: /export my data/i })).toBeVisible();
      });

      test('should display danger zone with delete account button', async ({ page }) => {
        await expect(page.getByText('Danger Zone')).toBeVisible();
        await expect(page.getByRole('button', { name: /delete account/i })).toBeVisible();
      });

      test('should open change password dialog', async ({ page }) => {
        await page.getByRole('button', { name: /change password/i }).click();

        // Dialog should appear
        await expect(page.getByText(/enter your current password/i)).toBeVisible({ timeout: 5_000 });
        await expect(page.getByLabel(/current password/i)).toBeVisible();
        await expect(page.getByLabel(/new password/i)).toBeVisible();
        await expect(page.getByLabel(/confirm.*password/i)).toBeVisible();
      });

      test('should close change password dialog on cancel', async ({ page }) => {
        await page.getByRole('button', { name: /change password/i }).click();
        await expect(page.getByLabel(/current password/i)).toBeVisible({ timeout: 5_000 });

        await page.getByRole('button', { name: /cancel/i }).click();
        await expect(page.getByLabel(/current password/i)).not.toBeVisible({ timeout: 3_000 });
      });

      test('should open delete account dialog', async ({ page }) => {
        await page.getByRole('button', { name: /delete account/i }).click();

        // Dialog should appear
        await expect(
          page.getByText(/this action cannot be undone/i)
        ).toBeVisible({ timeout: 5_000 });
        await expect(page.getByLabel(/type.*delete.*confirm/i)).toBeVisible();
      });

      test('should require DELETE confirmation to enable delete button', async ({ page }) => {
        await page.getByRole('button', { name: /delete account/i }).click();
        await expect(page.getByLabel(/type.*delete.*confirm/i)).toBeVisible({ timeout: 5_000 });

        // Delete button in dialog should be disabled initially
        const dialogDeleteBtn = page.locator('[role="dialog"]').getByRole('button', { name: /delete account/i });
        await expect(dialogDeleteBtn).toBeDisabled();

        // Type DELETE to enable it
        await page.getByPlaceholder('DELETE').fill('DELETE');
        await expect(dialogDeleteBtn).toBeEnabled();
      });

      test('should show login history table when history exists', async ({ page }) => {
        // Check for either table or "no login history" message
        const table = page.locator('table');
        const noHistory = page.getByText(/no login history/i);

        const tableVisible = await table.isVisible().catch(() => false);
        const noHistoryVisible = await noHistory.isVisible().catch(() => false);

        expect(tableVisible || noHistoryVisible).toBeTruthy();

        if (tableVisible) {
          await expect(page.getByText(/date.*time/i)).toBeVisible();
          await expect(page.getByText(/ip address/i)).toBeVisible();
          await expect(page.getByText(/status/i)).toBeVisible();
        }
      });
    });
  });
});
