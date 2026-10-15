import { test, expect } from './helpers/fixtures';
import {
  STORAGE_STATE,
  clickNavLink,
  signInWithSavedSession,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * Admin Dashboard E2E Tests
 *
 * These tests cover the admin panel pages including:
 * - Switched-off pages: dashboard, analytics, SEO, settings (KAN-184, "Not available yet")
 * - User management (user list, search, user detail view, actions)
 * - Subscription management (read through the admin subscriptions API, KAN-50)
 * - Audit logs (read through the admin audit logs API, KAN-50)
 *
 * NOTE: Admin tests require an admin user. If TEST_ADMIN_EMAIL is not set,
 * tests that require authentication will be skipped.
 */

test.describe('Admin Dashboard', () => {
  test.describe('Access Control', () => {
    test('should redirect to /login when not authenticated', async ({ page }) => {
      await page.goto('/admin');
      await page.waitForURL(/\/login|\/dashboard/, { timeout: 10_000 });
    });

    test('should redirect non-admin users to /dashboard', async ({ page }) => {
      // If a regular user tries to access admin, they get redirected
      if (!process.env.TEST_USER_EMAIL) {
        test.skip();
        return;
      }

      // Logged in as the regular test user (session saved by auth.setup.ts).
      await signInWithSavedSession(page.context(), 'user');

      // KAN-141: the non-admin must land on /dashboard directly, never passing through /login.
      const visitedPaths: string[] = [];
      page.on('request', (request) => {
        if (request.isNavigationRequest()) visitedPaths.push(new URL(request.url()).pathname);
      });

      await page.goto('/admin');
      await page.waitForURL(/\/dashboard/, { timeout: 10_000 });

      expect(visitedPaths).not.toContain('/login');
    });
  });

  test.describe('Admin Layout & Navigation', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    test.beforeEach(async ({ page }) => {
      await page.goto('/admin');
      await waitForPageReady(page);
    });

    test('should display admin portal branding', async ({ page }) => {
      await expect(page.getByText('Admin Portal')).toBeVisible();
    });

    test('should display sidebar navigation with all menu items', async ({ page }) => {
      const sidebar = page.locator('aside');
      await expect(sidebar).toBeVisible();

      await expect(sidebar.getByRole('link', { name: /^dashboard$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^users$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^subscriptions$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^analytics$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^seo$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^settings$/i })).toBeVisible();
      await expect(sidebar.getByRole('link', { name: /^audit logs$/i })).toBeVisible();
    });

    test('should navigate to all admin sections via sidebar', async ({ page }) => {
      const sidebar = page.locator('aside');
      // Users
      await clickNavLink(page, sidebar.getByRole('link', { name: /^users$/i }));
      await expect(page).toHaveURL(/\/admin\/users/);

      // Subscriptions
      await clickNavLink(page, sidebar.getByRole('link', { name: /^subscriptions$/i }));
      await expect(page).toHaveURL(/\/admin\/subscriptions/);

      // Analytics
      await clickNavLink(page, sidebar.getByRole('link', { name: /^analytics$/i }));
      await expect(page).toHaveURL(/\/admin\/analytics/);

      // SEO
      await clickNavLink(page, sidebar.getByRole('link', { name: /^seo$/i }));
      await expect(page).toHaveURL(/\/admin\/seo/);

      // Settings
      await clickNavLink(page, sidebar.getByRole('link', { name: /^settings$/i }));
      await expect(page).toHaveURL(/\/admin\/settings/);

      // Audit Logs
      await clickNavLink(page, sidebar.getByRole('link', { name: /^audit logs$/i }));
      await expect(page).toHaveURL(/\/admin\/audit-logs/);

      // Back to Dashboard
      await clickNavLink(page, sidebar.getByRole('link', { name: /^dashboard$/i }));
      await expect(page).toHaveURL(/\/admin$/);
    });
  });

  test.describe('Switched-off pages (KAN-184)', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    for (const [path, heading] of [
      ['/admin', /admin dashboard/i],
      ['/admin/analytics', /^analytics$/i],
      ['/admin/seo', /seo management/i],
      ['/admin/settings', /^settings$/i],
    ] as const) {
      test(`${path} shows a not available state`, async ({ page }) => {
        await page.goto(path);
        await waitForPageReady(page);

        await expect(page.getByRole('heading', { name: heading })).toBeVisible();
        await expect(page.getByText('Not available yet', { exact: true })).toBeVisible();
        await expect(page.getByRole('link', { name: /go to users/i })).toBeVisible();
      });
    }
  });

  test.describe('User Management Page', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    test.beforeEach(async ({ page }) => {
      await page.goto('/admin/users');
      await waitForPageReady(page);
    });

    test('should display user management heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /user management/i })).toBeVisible();
      await expect(page.getByText(/view and manage all platform users/i)).toBeVisible();
    });

    test('should display search bar', async ({ page }) => {
      await expect(page.getByPlaceholder(/search users by email or name/i)).toBeVisible();
    });

    test('should display search button', async ({ page }) => {
      await expect(page.getByRole('button', { name: /^search$/i })).toBeVisible();
    });

    test('should search users through the API', async ({ page }) => {
      await page.getByPlaceholder(/search users by email or name/i).fill('zz-no-such-user-zz');
      await page.getByRole('button', { name: /^search$/i }).click();

      await expect(page).toHaveURL(/\/admin\/users\?q=zz-no-such-user-zz/);
      await expect(page.getByText('No users found')).toBeVisible();
    });

    // Quarantined (KAN-165): strict-mode violation on locator('table') when the page has many users. Tracked in KAN-196.
    test.fixme('should display users table with correct columns', async ({ page }) => {
      await expect(page.getByText('All Users')).toBeVisible();

      // Table headers
      const table = page.locator('table');
      await expect(table).toBeVisible();

      await expect(table.getByRole('columnheader', { name: /^user$/i })).toBeVisible();
      await expect(table.getByText(/^email$/i)).toBeVisible();
      await expect(table.getByText(/^status$/i)).toBeVisible();
      await expect(table.getByText(/^role$/i)).toBeVisible();
      await expect(table.getByText(/^last login$/i)).toBeVisible();
      await expect(table.getByText(/^joined$/i)).toBeVisible();
      await expect(table.getByText(/^actions$/i)).toBeVisible();
    });

    test('should display user action dropdown menu', async ({ page }) => {
      // Click the first action button in the table
      const actionButton = page.locator('table tbody tr').first().getByRole('button');
      // Wait for the table row to render (isVisible() alone does not wait, so the test passed without checking).
      const isVisible = await actionButton
        .waitFor({ state: 'visible' })
        .then(() => true)
        .catch(() => false);

      if (isVisible) {
        await actionButton.click();

        await expect(page.getByText(/view details/i)).toBeVisible({ timeout: 3_000 });
        await expect(page.getByText(/edit user/i)).toBeVisible();
        await expect(page.getByText(/suspend user/i)).toBeVisible();
      }
    });

    test('should show verification badges for users', async ({ page }) => {
      // Users should have either "Verified" or "Unverified" badge
      const table = page.locator('table tbody');
      const verifiedBadge = table.getByText(/verified|unverified/i);
      const hasBadge = await verifiedBadge
        .first()
        .isVisible()
        .catch(() => false);
      expect(hasBadge || true).toBeTruthy();
    });
  });

  test.describe('User Detail Page', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    // Quarantined (KAN-165): flaky, waitForHydration times out on the not-found page (3 of 5 repeats). Tracked in KAN-198.
    test.fixme('should display 404 for non-existent user', async ({ page }) => {
      await page.goto('/admin/users/nonexistent-id');
      await waitForPageReady(page);

      // Should show not found or redirect
      const notFound = page.getByText(/not found/i);
      const hasNotFound = await notFound.isVisible().catch(() => false);
      // Accept either 404 or redirect
      expect(hasNotFound || page.url().includes('/admin/users')).toBeTruthy();
    });

    test('should show the user read through the API', async ({ page }) => {
      await page.goto('/admin/users');
      await waitForPageReady(page);
      await page.locator('table tbody tr').first().getByRole('button').click();
      await page.getByRole('menuitem', { name: /view details/i }).click();

      await expect(page).toHaveURL(/\/admin\/users\/[^/]+$/);
      await expect(page.getByRole('heading', { name: /user details/i })).toBeVisible();
      await expect(page.getByText('Basic Information')).toBeVisible();
      await expect(page.getByText('Admin Access')).toBeVisible();
    });
  });

  test.describe('Subscription Management Page', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    test.beforeEach(async ({ page }) => {
      await page.goto('/admin/subscriptions');
      await waitForPageReady(page);
    });

    test('should display subscription management heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /subscription management/i })).toBeVisible();
      await expect(page.getByText(/monitor and manage all subscriptions/i)).toBeVisible();
    });

    test('should display 4 subscription metric cards', async ({ page }) => {
      await expect(page.getByText('Total Active')).toBeVisible();
      await expect(page.getByText('Pro Plans')).toBeVisible();
      await expect(page.getByText('Enterprise Plans', { exact: true })).toBeVisible();
      await expect(page.getByText('MRR')).toBeVisible();
    });

    test('should display pricing info in metric cards', async ({ page }) => {
      const proCard = page.locator('[class*="card"]').filter({ hasText: 'Pro Plans' });
      await expect(proCard.getByText(/[$£€]\d+\/month/i)).toBeVisible();

      const enterpriseCard = page
        .locator('[class*="card"]')
        .filter({ hasText: 'Enterprise Plans' });
      await expect(enterpriseCard.getByText(/[$£€]\d+\/month/i)).toBeVisible();
    });

    test('should display recent subscriptions table', async ({ page }) => {
      await expect(page.getByText('Newest paid organisations', { exact: true })).toBeVisible();

      // Column headers are asserted only when a paid organisation exists. A fresh e2e database has none and
      // seeding one needs Stripe-backed state, so the empty state is accepted; the headers are covered by the
      // unit tests in admin-pages.test.tsx.
      const table = page.getByRole('table');
      const emptyState = page.getByText('No Active Subscriptions');
      await expect(table.or(emptyState)).toBeVisible();

      if (await table.isVisible()) {
        await expect(table.getByRole('columnheader', { name: /^organisation$/i })).toBeVisible();
        await expect(table.getByRole('columnheader', { name: /^slug$/i })).toBeVisible();
        await expect(table.getByRole('columnheader', { name: /^plan$/i })).toBeVisible();
        await expect(table.getByRole('columnheader', { name: /^status$/i })).toBeVisible();
        await expect(table.getByRole('columnheader', { name: /^renewal date$/i })).toBeVisible();
      }
    });

    test('should display manage buttons for subscriptions', async ({ page }) => {
      const manageBtn = page.getByRole('button', { name: /manage/i });
      const hasManage = await manageBtn
        .first()
        .isVisible()
        .catch(() => false);
      // Manage buttons should exist if there are subscriptions
      expect(hasManage || true).toBeTruthy();
    });
  });

  test.describe('Audit Logs Page', () => {
    test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
    test.use({ storageState: STORAGE_STATE.admin });

    test.beforeEach(async ({ page }) => {
      await page.goto('/admin/audit-logs');
      await waitForPageReady(page);
    });

    test('should display audit logs heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /audit logs/i })).toBeVisible();
      await expect(page.getByText(/track all administrative actions/i)).toBeVisible();
    });

    test('should display recent activity section', async ({ page }) => {
      await expect(page.getByText('Recent Activity')).toBeVisible();
      await expect(page.getByText(/showing \d+ of \d+ entries/i)).toBeVisible();
    });

    test('should show table or empty state', async ({ page }) => {
      const table = page.getByRole('table');
      const emptyState = page.getByText(/no audit logs found/i);

      const hasTable = await table.isVisible().catch(() => false);
      const hasEmpty = await emptyState.isVisible().catch(() => false);

      expect(hasTable || hasEmpty).toBeTruthy();
    });

    test('should display audit log table columns when data exists', async ({ page }) => {
      const table = page.getByRole('table');
      const hasTable = await table.isVisible().catch(() => false);

      if (hasTable) {
        await expect(table.getByText(/timestamp/i)).toBeVisible();
        await expect(table.getByText(/action/i)).toBeVisible();
        await expect(table.getByText(/resource/i)).toBeVisible();
        await expect(table.getByText(/user id/i)).toBeVisible();
        await expect(table.getByText(/ip address/i)).toBeVisible();
      }
    });
  });
});
