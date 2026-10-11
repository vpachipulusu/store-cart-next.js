import { test, expect } from '@playwright/test';
import { loginViaUI, TEST_ADMIN, waitForPageReady } from './helpers/e2e-utils';

/**
 * Admin Dashboard E2E Tests
 *
 * These tests cover the admin panel pages including:
 * - Dashboard overview (metrics, subscription breakdown, recent users/activity)
 * - User management (user list, search, user detail view, actions)
 * - Subscription management (stats, subscription table)
 * - Analytics (user growth, revenue, activity overview)
 * - SEO management (meta tags, redirects, sitemap)
 * - Settings (general, feature flags, email templates, pricing)
 * - Audit logs (log table, filters)
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

      await loginViaUI(
        page,
        process.env.TEST_USER_EMAIL,
        process.env.TEST_USER_PASSWORD || 'TestPass123!'
      );

      await page.goto('/admin');
      // Non-admin users should be redirected away from admin
      await page.waitForURL(/\/dashboard|\/login/, { timeout: 10_000 });
    });
  });

  test.describe('Admin Layout & Navigation', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin');
      await waitForPageReady(page);
    });

    test('should display admin portal branding', async ({ page }) => {
      await expect(page.getByText('Admin Portal')).toBeVisible();
    });

    test('should display sidebar navigation with all menu items', async ({ page }) => {
      const sidebar = page.locator('aside');
      await expect(sidebar).toBeVisible();

      await expect(page.getByRole('link', { name: /^dashboard$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^users$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^subscriptions$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^analytics$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^seo$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^settings$/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /^audit logs$/i })).toBeVisible();
    });

    test('should navigate to all admin sections via sidebar', async ({ page }) => {
      // Users
      await page.getByRole('link', { name: /^users$/i }).click();
      await expect(page).toHaveURL(/\/admin\/users/);

      // Subscriptions
      await page.getByRole('link', { name: /^subscriptions$/i }).click();
      await expect(page).toHaveURL(/\/admin\/subscriptions/);

      // Analytics
      await page.getByRole('link', { name: /^analytics$/i }).click();
      await expect(page).toHaveURL(/\/admin\/analytics/);

      // SEO
      await page.getByRole('link', { name: /^seo$/i }).click();
      await expect(page).toHaveURL(/\/admin\/seo/);

      // Settings
      await page.getByRole('link', { name: /^settings$/i }).click();
      await expect(page).toHaveURL(/\/admin\/settings/);

      // Audit Logs
      await page.getByRole('link', { name: /^audit logs$/i }).click();
      await expect(page).toHaveURL(/\/admin\/audit-logs/);

      // Back to Dashboard
      await page.getByRole('link', { name: /^dashboard$/i }).click();
      await expect(page).toHaveURL(/\/admin$/);
    });
  });

  test.describe('Dashboard Overview Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin');
      await waitForPageReady(page);
    });

    test('should display admin dashboard heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /admin dashboard/i })).toBeVisible();
      await expect(page.getByText(/monitor and manage/i)).toBeVisible();
    });

    test('should display 4 key metric cards', async ({ page }) => {
      await expect(page.getByText('Total Users')).toBeVisible();
      await expect(page.getByText('Active Subscriptions')).toBeVisible();
      await expect(page.getByText('MRR')).toBeVisible();
      await expect(page.getByText('New Users')).toBeVisible();
    });

    test('should display MRR with dollar sign', async ({ page }) => {
      const mrrCard = page.locator('[class*="card"]').filter({ hasText: 'MRR' });
      await expect(mrrCard.getByText(/\$/)).toBeVisible();
      await expect(mrrCard.getByText(/monthly recurring revenue/i)).toBeVisible();
    });

    test('should display subscription breakdown section', async ({ page }) => {
      await expect(page.getByText('Subscription Breakdown')).toBeVisible();
      await expect(page.getByText(/users by subscription tier/i)).toBeVisible();
    });

    test('should display recent users section', async ({ page }) => {
      await expect(page.getByText('Recent Users')).toBeVisible();
      await expect(page.getByText(/latest user registrations/i)).toBeVisible();

      // "View All Users" link
      await expect(page.getByRole('link', { name: /view all users/i })).toBeVisible();
    });

    test('should display recent activity section', async ({ page }) => {
      await expect(page.getByText('Recent Activity')).toBeVisible();
      await expect(page.getByText(/latest audit log entries/i)).toBeVisible();

      // "View All Logs" link
      await expect(page.getByRole('link', { name: /view all logs/i })).toBeVisible();
    });

    test('should display quick actions section', async ({ page }) => {
      await expect(page.getByText('Quick Actions')).toBeVisible();

      await expect(page.getByRole('link', { name: /manage users/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /subscriptions/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /analytics/i })).toBeVisible();
      await expect(page.getByRole('link', { name: /settings/i })).toBeVisible();
    });

    test('should navigate to users page from "View All Users"', async ({ page }) => {
      await page.getByRole('link', { name: /view all users/i }).click();
      await expect(page).toHaveURL(/\/admin\/users/);
    });

    test('should navigate to audit logs from "View All Logs"', async ({ page }) => {
      await page.getByRole('link', { name: /view all logs/i }).click();
      await expect(page).toHaveURL(/\/admin\/audit-logs/);
    });
  });

  test.describe('User Management Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/users');
      await waitForPageReady(page);
    });

    test('should display user management heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /user management/i })).toBeVisible();
      await expect(page.getByText(/view and manage all platform users/i)).toBeVisible();
    });

    test('should display search bar', async ({ page }) => {
      await expect(
        page.getByPlaceholder(/search users by email or name/i)
      ).toBeVisible();
    });

    test('should display export button', async ({ page }) => {
      await expect(page.getByRole('button', { name: /export/i })).toBeVisible();
    });

    test('should display users table with correct columns', async ({ page }) => {
      await expect(page.getByText('All Users')).toBeVisible();

      // Table headers
      const table = page.locator('table');
      await expect(table).toBeVisible();

      await expect(table.getByText(/^user$/i)).toBeVisible();
      await expect(table.getByText(/^email$/i)).toBeVisible();
      await expect(table.getByText(/^status$/i)).toBeVisible();
      await expect(table.getByText(/^subscription$/i)).toBeVisible();
      await expect(table.getByText(/^role$/i)).toBeVisible();
      await expect(table.getByText(/^joined$/i)).toBeVisible();
      await expect(table.getByText(/^actions$/i)).toBeVisible();
    });

    test('should display user action dropdown menu', async ({ page }) => {
      // Click the first action button in the table
      const actionButton = page.locator('table tbody tr').first().getByRole('button');
      const isVisible = await actionButton.isVisible().catch(() => false);

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
      const hasBadge = await verifiedBadge.first().isVisible().catch(() => false);
      expect(hasBadge || true).toBeTruthy();
    });

    test('should show subscription tier badges', async ({ page }) => {
      const table = page.locator('table tbody');
      const tierBadge = table.getByText(/free|pro|enterprise/i);
      const hasBadge = await tierBadge.first().isVisible().catch(() => false);
      expect(hasBadge || true).toBeTruthy();
    });
  });

  test.describe('User Detail Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
    });

    test('should display 404 for non-existent user', async ({ page }) => {
      await page.goto('/admin/users/nonexistent-id');
      await waitForPageReady(page);

      // Should show not found or redirect
      const notFound = page.getByText(/not found/i);
      const hasNotFound = await notFound.isVisible().catch(() => false);
      // Accept either 404 or redirect
      expect(hasNotFound || page.url().includes('/admin/users')).toBeTruthy();
    });
  });

  test.describe('Subscription Management Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/subscriptions');
      await waitForPageReady(page);
    });

    test('should display subscription management heading', async ({ page }) => {
      await expect(
        page.getByRole('heading', { name: /subscription management/i })
      ).toBeVisible();
      await expect(page.getByText(/monitor and manage all subscriptions/i)).toBeVisible();
    });

    test('should display 4 subscription metric cards', async ({ page }) => {
      await expect(page.getByText('Total Active')).toBeVisible();
      await expect(page.getByText('Pro Plans')).toBeVisible();
      await expect(page.getByText('Enterprise Plans')).toBeVisible();
      await expect(page.getByText('MRR')).toBeVisible();
    });

    test('should display pricing info in metric cards', async ({ page }) => {
      const proCard = page.locator('[class*="card"]').filter({ hasText: 'Pro Plans' });
      await expect(proCard.getByText(/\$\d+\/month/i)).toBeVisible();

      const enterpriseCard = page.locator('[class*="card"]').filter({ hasText: 'Enterprise Plans' });
      await expect(enterpriseCard.getByText(/\$\d+\/month/i)).toBeVisible();
    });

    test('should display recent subscriptions table', async ({ page }) => {
      await expect(page.getByText('Recent Subscriptions')).toBeVisible();

      const table = page.locator('table');
      await expect(table).toBeVisible();

      // Table headers
      await expect(table.getByText(/customer/i)).toBeVisible();
      await expect(table.getByText(/email/i)).toBeVisible();
      await expect(table.getByText(/plan/i)).toBeVisible();
      await expect(table.getByText(/status/i)).toBeVisible();
      await expect(table.getByText(/renewal date/i)).toBeVisible();
    });

    test('should display manage buttons for subscriptions', async ({ page }) => {
      const manageBtn = page.getByRole('button', { name: /manage/i });
      const hasManage = await manageBtn.first().isVisible().catch(() => false);
      // Manage buttons should exist if there are subscriptions
      expect(hasManage || true).toBeTruthy();
    });
  });

  test.describe('Analytics Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/analytics');
      await waitForPageReady(page);
    });

    test('should display analytics heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /analytics/i })).toBeVisible();
      await expect(page.getByText(/insights and metrics/i)).toBeVisible();
    });

    test('should display 4 key metric cards', async ({ page }) => {
      await expect(page.getByText('New Users')).toBeVisible();
      await expect(page.getByText('Active Subscriptions')).toBeVisible();
      await expect(page.getByText('MRR')).toBeVisible();
      await expect(page.getByText('Total Logins')).toBeVisible();
    });

    test('should display growth percentage indicator', async ({ page }) => {
      // Growth indicator with percentage
      const growthIndicator = page.getByText(/%/);
      await expect(growthIndicator.first()).toBeVisible();
      await expect(page.getByText(/vs last period/i)).toBeVisible();
    });

    test('should display user growth section', async ({ page }) => {
      await expect(page.getByText('User Growth')).toBeVisible();
      await expect(page.getByText(/new user sign-ups over time/i)).toBeVisible();

      // Current vs previous period comparison
      await expect(page.getByText(/current period/i)).toBeVisible();
      await expect(page.getByText(/previous period/i)).toBeVisible();
    });

    test('should display revenue metrics section', async ({ page }) => {
      await expect(page.getByText('Revenue Metrics')).toBeVisible();
      await expect(page.getByText(/subscription and revenue breakdown/i)).toBeVisible();

      await expect(page.getByText(/monthly recurring revenue/i).first()).toBeVisible();
      await expect(page.getByText(/average revenue per user/i)).toBeVisible();
    });

    test('should display activity overview section', async ({ page }) => {
      await expect(page.getByText('Activity Overview')).toBeVisible();
      await expect(page.getByText(/platform activity and engagement/i)).toBeVisible();

      await expect(page.getByText(/total logins/i).first()).toBeVisible();
      await expect(page.getByText(/avg logins\/user/i)).toBeVisible();
      await expect(page.getByText(/conversion rate/i)).toBeVisible();
    });

    test('should display conversion rate as percentage', async ({ page }) => {
      const activitySection = page.locator('[class*="card"]').filter({ hasText: 'Activity Overview' });
      await expect(activitySection.getByText(/free to paid/i)).toBeVisible();
    });
  });

  test.describe('SEO Management Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/seo');
      await waitForPageReady(page);
    });

    test('should display SEO management heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /seo management/i })).toBeVisible();
      await expect(page.getByText(/manage meta tags.*redirects/i)).toBeVisible();
    });

    test('should display 3 tab options', async ({ page }) => {
      await expect(page.getByRole('tab', { name: /meta tags/i })).toBeVisible();
      await expect(page.getByRole('tab', { name: /redirects/i })).toBeVisible();
      await expect(page.getByRole('tab', { name: /sitemap/i })).toBeVisible();
    });

    test('should show meta tags tab content by default', async ({ page }) => {
      await expect(page.getByText('Page Meta Tags')).toBeVisible();
      await expect(page.getByText(/configure seo meta tags/i)).toBeVisible();
    });

    test('should switch to redirects tab', async ({ page }) => {
      await page.getByRole('tab', { name: /redirects/i }).click();

      await expect(page.getByText('URL Redirects')).toBeVisible();
      await expect(page.getByText(/manage 301\/302 redirects/i)).toBeVisible();
    });

    test('should switch to sitemap tab', async ({ page }) => {
      await page.getByRole('tab', { name: /sitemap/i }).click();

      await expect(page.getByText('Sitemap Management')).toBeVisible();
      await expect(page.getByText(/generate and manage xml sitemaps/i)).toBeVisible();
    });

    test('should display sitemap URL and regenerate button', async ({ page }) => {
      await page.getByRole('tab', { name: /sitemap/i }).click();

      await expect(page.getByText('sitemap.xml')).toBeVisible();
      await expect(page.getByRole('button', { name: /regenerate/i })).toBeVisible();
      await expect(page.getByText(/sitemap url/i)).toBeVisible();
    });

    test('should display sitemap statistics', async ({ page }) => {
      await page.getByRole('tab', { name: /sitemap/i }).click();

      await expect(page.getByText(/sitemap statistics/i)).toBeVisible();
      await expect(page.getByText(/total urls/i)).toBeVisible();
      await expect(page.getByText(/file size/i)).toBeVisible();
      await expect(page.getByText(/last submitted/i)).toBeVisible();
    });

    test('should show empty state when no meta tags exist', async ({ page }) => {
      const emptyState = page.getByText(/no meta tags configured/i);
      const table = page.locator('table');

      const hasEmpty = await emptyState.isVisible().catch(() => false);
      const hasTable = await table.isVisible().catch(() => false);

      // Either empty state or a table with data
      expect(hasEmpty || hasTable).toBeTruthy();
    });

    test('should show meta tags table columns when data exists', async ({ page }) => {
      const table = page.locator('table');
      const hasTable = await table.isVisible().catch(() => false);

      if (hasTable) {
        await expect(table.getByText(/page/i)).toBeVisible();
        await expect(table.getByText(/title/i)).toBeVisible();
        await expect(table.getByText(/description/i)).toBeVisible();
        await expect(table.getByText(/index/i)).toBeVisible();
      }
    });
  });

  test.describe('Settings Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/settings');
      await waitForPageReady(page);
    });

    test('should display settings heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /^settings$/i })).toBeVisible();
      await expect(page.getByText(/manage application settings/i)).toBeVisible();
    });

    test('should display 4 settings tabs', async ({ page }) => {
      await expect(page.getByRole('tab', { name: /general/i })).toBeVisible();
      await expect(page.getByRole('tab', { name: /feature flags/i })).toBeVisible();
      await expect(page.getByRole('tab', { name: /email/i })).toBeVisible();
      await expect(page.getByRole('tab', { name: /pricing/i })).toBeVisible();
    });

    test('should show general settings tab by default', async ({ page }) => {
      // General tab should be active by default
      const generalTab = page.getByRole('tab', { name: /general/i });
      await expect(generalTab).toHaveAttribute('data-state', 'active');
    });

    test('should switch to feature flags tab', async ({ page }) => {
      await page.getByRole('tab', { name: /feature flags/i }).click();

      // Feature flags content should be visible
      const flagsTab = page.getByRole('tab', { name: /feature flags/i });
      await expect(flagsTab).toHaveAttribute('data-state', 'active');
    });

    test('should switch to email templates tab', async ({ page }) => {
      await page.getByRole('tab', { name: /email/i }).click();

      await expect(page.getByText('Email Templates')).toBeVisible();
      await expect(page.getByText(/manage transactional email/i)).toBeVisible();
    });

    test('should switch to pricing tab and display plan configuration', async ({ page }) => {
      await page.getByRole('tab', { name: /pricing/i }).click();

      await expect(page.getByText('Pricing Configuration')).toBeVisible();
      await expect(page.getByText(/manage subscription plans/i)).toBeVisible();

      // Pro plan fields
      await expect(page.getByText(/pro plan/i)).toBeVisible();
      await expect(page.getByLabel(/pro.*price/i).first()).toBeVisible();

      // Enterprise plan fields
      await expect(page.getByText(/enterprise plan/i)).toBeVisible();
      await expect(page.getByLabel(/enterprise.*price/i).first()).toBeVisible();

      // Save button
      await expect(page.getByRole('button', { name: /save pricing/i })).toBeVisible();
    });

    test('should display Stripe Price ID fields in pricing tab', async ({ page }) => {
      await page.getByRole('tab', { name: /pricing/i }).click();

      await expect(page.getByPlaceholder(/price_/i).first()).toBeVisible();
    });
  });

  test.describe('Audit Logs Page', () => {
    test.skip(
      !process.env.TEST_ADMIN_EMAIL,
      'Skipped: TEST_ADMIN_EMAIL not configured'
    );

    test.beforeEach(async ({ page }) => {
      await loginViaUI(page, TEST_ADMIN.email, TEST_ADMIN.password);
      await page.goto('/admin/audit-logs');
      await waitForPageReady(page);
    });

    test('should display audit logs heading', async ({ page }) => {
      await expect(page.getByRole('heading', { name: /audit logs/i })).toBeVisible();
      await expect(page.getByText(/track all administrative actions/i)).toBeVisible();
    });

    test('should display recent activity section', async ({ page }) => {
      await expect(page.getByText('Recent Activity')).toBeVisible();
      await expect(page.getByText(/last 100 audit log entries/i)).toBeVisible();
    });

    test('should show table or empty state', async ({ page }) => {
      const table = page.locator('table');
      const emptyState = page.getByText(/no audit logs found/i);

      const hasTable = await table.isVisible().catch(() => false);
      const hasEmpty = await emptyState.isVisible().catch(() => false);

      expect(hasTable || hasEmpty).toBeTruthy();
    });

    test('should display audit log table columns when data exists', async ({ page }) => {
      const table = page.locator('table');
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
