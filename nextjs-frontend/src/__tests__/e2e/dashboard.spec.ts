import { test, expect } from './helpers/fixtures';
import { STORAGE_STATE, clickNavLink, waitForPageReady } from './helpers/e2e-utils';

/**
 * Customer Dashboard E2E Tests
 *
 * These tests cover the customer-facing dashboard pages including:
 * - Dashboard Overview (key figures, setup checklist, plan usage, account links)
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
      test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
      test.use({ storageState: STORAGE_STATE.user });

      test.beforeEach(async ({ page }) => {
        await page.goto('/dashboard');
        await waitForPageReady(page);
      });

      test('should display one h1 welcoming the user', async ({ page }) => {
        await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
        await expect(page.getByRole('heading', { level: 1 })).toContainText(/welcome back/i);
      });

      test('should display the empty-store key figures', async ({ page }) => {
        const strip = page.getByRole('list', { name: 'Key figures' });
        await expect(strip).toBeVisible();
        await expect(strip.getByRole('group')).toHaveCount(4);
        await expect(strip.getByText('No sales yet').first()).toBeVisible();
      });

      test('should show the setup checklist instead of an orders table', async ({ page }) => {
        const steps = page.getByRole('list', { name: 'Set up your store' });
        await expect(steps.getByRole('listitem')).toHaveCount(3);
        await expect(steps.getByText('Add a product')).toBeVisible();
        await expect(steps.getByText('Connect Stripe')).toBeVisible();
        await expect(steps.getByText('Add a domain')).toBeVisible();
        await expect(page.getByRole('table')).toHaveCount(0);
        await expect(page.getByText('Nothing needs attention')).toBeVisible();
      });

      test('should show the plan panel with its usage meters', async ({ page }) => {
        const plan = page.getByRole('region', { name: 'Plan', exact: true });
        await expect(plan).toBeVisible();
        await expect(plan.getByText(/ plan$/i).first()).toBeVisible();
        await expect(plan.getByRole('link', { name: 'Compare plans' })).toBeVisible();
      });

      test('should no longer show account info, login history or notifications', async ({
        page,
      }) => {
        for (const gone of ['Account Information', 'Recent Activity', 'Account Summary']) {
          await expect(page.getByText(gone)).toHaveCount(0);
        }
      });

      test('should link to Profile, Security and Settings from the page', async ({ page }) => {
        const main = page.locator('main');
        await expect(main.getByRole('link', { name: 'Profile', exact: true })).toHaveAttribute(
          'href',
          '/dashboard/profile'
        );
        await expect(main.getByRole('link', { name: 'Security', exact: true })).toHaveAttribute(
          'href',
          '/dashboard/security'
        );
        await expect(main.getByRole('link', { name: 'Settings', exact: true })).toHaveAttribute(
          'href',
          '/dashboard/settings'
        );
      });

      test('should navigate to security from the page link', async ({ page }) => {
        await page.locator('main').getByRole('link', { name: 'Security', exact: true }).click();
        await expect(page).toHaveURL(/\/dashboard\/security/);
      });
    });
  });

  test.describe('Dashboard Layout & Navigation', () => {
    test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
    test.skip(
      ({ isMobile }) => isMobile,
      'Sidebar is desktop only; phones are covered by dashboard-shell.spec.ts'
    );
    test.use({ storageState: STORAGE_STATE.user });

    test.beforeEach(async ({ page }) => {
      await page.goto('/dashboard');
      await waitForPageReady(page);
    });

    test('should display the workspace sidebar', async ({ page }) => {
      await expect(page.getByRole('complementary', { name: 'Workspace' })).toBeVisible();
    });

    test('should display navigation links', async ({ page }) => {
      const nav = page.getByRole('navigation', { name: 'Main' });
      await expect(nav).toBeVisible();

      // Scoped to the nav: the Overview page body also links to Profile, Security and Settings.
      await expect(nav.getByRole('link', { name: 'Overview', exact: true })).toBeVisible();
      await expect(nav.getByRole('link', { name: 'Profile', exact: true })).toBeVisible();
      await expect(nav.getByRole('link', { name: /settings/i }).first()).toBeVisible();
      await expect(nav.getByRole('link', { name: /security/i }).first()).toBeVisible();
    });

    test('should navigate between dashboard pages', async ({ page }) => {
      // Navigate to Profile
      await clickNavLink(page, page.getByRole('link', { name: /profile/i }).first());
      await expect(page).toHaveURL(/\/dashboard\/profile/);

      // Navigate to Settings
      await clickNavLink(page, page.getByRole('link', { name: /settings/i }).first());
      await expect(page).toHaveURL(/\/dashboard\/settings/);

      // Navigate to Security
      await clickNavLink(page, page.getByRole('link', { name: /security/i }).first());
      await expect(page).toHaveURL(/\/dashboard\/security/);

      // Navigate back to Overview
      await clickNavLink(page, page.getByRole('link', { name: 'Overview', exact: true }));
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
      test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
      test.use({ storageState: STORAGE_STATE.user });

      test.beforeEach(async ({ page }) => {
        await page.goto('/dashboard/profile');
        await waitForPageReady(page);
      });

      test('should display profile page heading', async ({ page }) => {
        await expect(page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible();
        await expect(page.getByText(/manage your public profile/i)).toBeVisible();
      });

      test('should have one h1 and no horizontal scroll at 375px', async ({ page }) => {
        await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
        await page.setViewportSize({ width: 375, height: 812 });
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth
        );
        expect(overflow).toBeLessThanOrEqual(0);
      });

      test('should show a success toast after saving', async ({ page }) => {
        await page.getByRole('button', { name: /save changes/i }).click();
        await expect(page.getByText(/profile updated successfully/i).first()).toBeVisible({
          timeout: 10_000,
        });
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

        await expect(page.getByText(/at least 2 characters/i)).toBeVisible({ timeout: 5_000 });
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

        await expect(page.getByText(/must not exceed 500 characters/i)).toBeVisible({
          timeout: 5_000,
        });
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
      test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
      test.use({ storageState: STORAGE_STATE.user });

      test.beforeEach(async ({ page }) => {
        await page.goto('/dashboard/settings');
        await waitForPageReady(page);
      });

      test('should display settings page heading', async ({ page }) => {
        await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
        await expect(page.getByText(/manage your account preferences/i)).toBeVisible();
      });

      test('should have one h1 and no horizontal scroll at 375px', async ({ page }) => {
        await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
        await page.setViewportSize({ width: 375, height: 812 });
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth
        );
        expect(overflow).toBeLessThanOrEqual(0);
      });

      test('should show a success toast after saving', async ({ page }) => {
        await page.getByRole('button', { name: /save settings/i }).click();
        await expect(page.getByText(/settings updated successfully/i).first()).toBeVisible({
          timeout: 10_000,
        });
      });

      test('should display appearance settings section', async ({ page }) => {
        await expect(page.getByText(/^appearance$/i)).toBeVisible();
        await expect(page.getByText(/customize how the app looks/i)).toBeVisible();
        await expect(page.getByLabel(/theme/i)).toBeVisible();
      });

      test('should display notification settings section', async ({ page }) => {
        await expect(page.getByText(/^notifications$/i).first()).toBeVisible();
        await expect(page.getByText('Email Notifications', { exact: true })).toBeVisible();
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
      test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');
      test.use({ storageState: STORAGE_STATE.user });

      test.beforeEach(async ({ page }) => {
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

      // KAN-41: 2FA setup/disable are switched off (KAN-180 re-authentication dialog; hidden while KAN-125 is
      // parked) and the 2FA status needs KAN-179. Re-enable this test with the controls.
      test.skip('should display two-factor authentication section', async ({ page }) => {
        await expect(page.getByText(/two-factor authentication/i).first()).toBeVisible();
        await expect(page.getByText(/2fa status/i)).toBeVisible();
        await expect(page.getByText(/sign-in does not check its codes yet/i)).toBeVisible();
        await expect(page.getByText(/need to enter both your password/i)).toHaveCount(0);

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

      // KAN-41: data export is switched off until KAN-114.
      test.skip('should display data export section', async ({ page }) => {
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
        await expect(page.getByText(/enter your current password/i)).toBeVisible({
          timeout: 5_000,
        });
        await expect(page.getByLabel(/current password/i)).toBeVisible();
        await expect(page.getByLabel('New Password', { exact: true })).toBeVisible();
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
        await expect(page.getByText(/this action cannot be undone/i)).toBeVisible({
          timeout: 5_000,
        });
        await expect(page.getByLabel(/type.*delete.*confirm/i)).toBeVisible();
      });

      test('should require DELETE and the password to enable delete button', async ({ page }) => {
        await page.getByRole('button', { name: /delete account/i }).click();
        await expect(page.getByLabel(/type.*delete.*confirm/i)).toBeVisible({ timeout: 5_000 });

        // Delete button in dialog should be disabled initially
        const dialogDeleteBtn = page
          .locator('[role="dialog"]')
          .getByRole('button', { name: /delete account/i });
        await expect(dialogDeleteBtn).toBeDisabled();

        // Type DELETE and re-enter the password (KAN-180) to enable it
        await page.getByPlaceholder('DELETE').fill('DELETE');
        await expect(dialogDeleteBtn).toBeDisabled();
        await page.getByLabel('Confirm your password').fill('not-submitted');
        await expect(dialogDeleteBtn).toBeEnabled();
      });

      test('should show login history table when history exists', async ({ page }) => {
        // Check for either table or "no login history" message
        const table = page.locator('table');
        const noHistory = page.getByText(/no login history/i);
        // Login history loads client-side after the page renders; wait for it to finish (either outcome).
        await expect(table.or(noHistory).first()).toBeVisible();

        const tableVisible = await table.isVisible().catch(() => false);
        const noHistoryVisible = await noHistory.isVisible().catch(() => false);

        expect(tableVisible || noHistoryVisible).toBeTruthy();

        if (tableVisible) {
          await expect(table.getByText(/date.*time/i)).toBeVisible();
          await expect(table.getByText(/ip address/i)).toBeVisible();
          await expect(table.getByText(/status/i)).toBeVisible();
        }
      });
    });
  });
});
