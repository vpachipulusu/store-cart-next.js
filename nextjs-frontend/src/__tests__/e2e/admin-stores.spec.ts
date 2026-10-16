import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import {
  STORAGE_STATE,
  expectToast,
  loginAsThrowawayAccount,
  signInWithSavedSession,
  waitForPageReady,
} from './helpers/e2e-utils';

/**
 * KAN-63: platform admin pages for organisations and stores (backend: KAN-201).
 *
 * - The listing tests need a backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and an admin account holding a
 *   `super_admin` grant (docs/developer/local-e2e.md). They create their own store through onboarding.
 * - Onboarding leaves a store PROVISIONING (nothing activates it until KAN-56), so the suspend, unsuspend and
 *   migrate flow needs a store that is already ACTIVE. Set E2E_ACTIVE_STORE_SLUG to the slug of one you made ACTIVE
 *   in your own throwaway database; without it that flow is skipped. The flow ends with the store ACTIVE again.
 * - Re-running provisioning is KAN-200 and has no control yet.
 */

const HAS_BACKEND = Boolean(process.env.BACKEND_INTERNAL_KEY);
const ACTIVE_STORE_SLUG = process.env.E2E_ACTIVE_STORE_SLUG;

async function searchStores(page: Page, slug: string): Promise<void> {
  await page.goto(`/admin/stores?q=${encodeURIComponent(slug)}`);
  await waitForPageReady(page);
}

test.describe('Admin stores and organisations', () => {
  test.skip(!process.env.TEST_ADMIN_EMAIL, 'Skipped: TEST_ADMIN_EMAIL not configured');
  test.skip(
    !HAS_BACKEND,
    'Skipped: BACKEND_INTERNAL_KEY / BACKEND_API_URL not set (needs FastAPI)'
  );

  test.describe('as a platform admin', () => {
    test.use({ storageState: STORAGE_STATE.admin });

    test('is reachable from the sidebar', async ({ page }) => {
      await page.goto('/admin');
      await waitForPageReady(page);

      await page.getByRole('link', { name: 'Stores', exact: true }).click();
      await expect(page).toHaveURL(/\/admin\/stores$/);
      await expect(page.getByRole('heading', { name: 'Stores', exact: true })).toBeVisible();

      await page.getByRole('link', { name: 'Organisations', exact: true }).click();
      await expect(page).toHaveURL(/\/admin\/organizations$/);
      await expect(page.getByRole('heading', { name: 'Organisations', exact: true })).toBeVisible();
    });

    test('lists stores with status and schema version columns', async ({ page }) => {
      await page.goto('/admin/stores');
      await waitForPageReady(page);

      const table = page.getByRole('table');
      await expect(table).toBeVisible();
      for (const name of ['Store', 'Organisation', 'Status', 'Schema version', 'Created']) {
        await expect(table.getByRole('columnheader', { name, exact: true })).toBeVisible();
      }
      await expect(table.getByRole('columnheader', { name: 'Actions' })).toBeVisible();
    });

    test('shows an empty state for a search with no match', async ({ page }) => {
      await searchStores(page, 'zz-no-such-store-zz');

      await expect(page.getByText('No stores found')).toBeVisible();
    });

    test('ignores an unknown status filter instead of failing', async ({ page }) => {
      await page.goto('/admin/stores?status=NOT_A_STATUS');
      await waitForPageReady(page);

      await expect(page.getByRole('heading', { name: 'Stores', exact: true })).toBeVisible();
      // The route announcer also has role "alert"; only the page's own error message counts.
      await expect(page.locator('main [role="alert"]')).toHaveCount(0);
    });

    test('suspends, migrates and unsuspends an active store', async ({ page }) => {
      test.skip(
        !ACTIVE_STORE_SLUG,
        'Skipped: E2E_ACTIVE_STORE_SLUG not set (needs an ACTIVE store)'
      );
      await searchStores(page, ACTIVE_STORE_SLUG!);

      const row = page.getByRole('row').filter({ hasText: ACTIVE_STORE_SLUG! });
      await expect(row.getByText('Active', { exact: true })).toBeVisible();

      try {
        // Migrations are safe to repeat and say which versions they moved between.
        await row.getByRole('button', { name: /^run migrations for/i }).click();
        await expectToast(page, /schema/i);

        // Cancelling the confirmation changes nothing.
        await row.getByRole('button', { name: /^suspend /i }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByText(/storefront goes offline/i)).toBeVisible();
        await dialog.getByRole('button', { name: 'Cancel' }).click();
        await expect(dialog).toHaveCount(0);
        await expect(row.getByText('Active', { exact: true })).toBeVisible();

        // Confirming suspends the store and offers unsuspend instead.
        await row.getByRole('button', { name: /^suspend /i }).click();
        await page.getByRole('dialog').getByRole('button', { name: 'Suspend store' }).click();
        await expectToast(page, 'Store suspended');
        await expect(row.getByText('Suspended', { exact: true })).toBeVisible();
        await expect(row.getByRole('button', { name: /^unsuspend /i })).toBeVisible();
        await expect(row.getByRole('button', { name: /^run migrations for/i })).toBeVisible();

        await row.getByRole('button', { name: /^unsuspend /i }).click();
        await expectToast(page, 'Store unsuspended');
        await expect(row.getByText('Active', { exact: true })).toBeVisible();
      } finally {
        // A run that stopped half way must not leave the shared store suspended.
        await page.goto(`/admin/stores?q=${encodeURIComponent(ACTIVE_STORE_SLUG!)}`);
        const unsuspend = row.getByRole('button', { name: /^unsuspend /i });
        if (await unsuspend.isVisible()) {
          await unsuspend.click();
          await expect(unsuspend).toHaveCount(0);
        }
      }
    });
  });

  test.describe('a newly onboarded merchant', () => {
    test('appears in both admin lists, with no actions while provisioning', async ({
      page,
      throwawayAccount,
    }) => {
      const suffix = throwawayAccount.email.split('@')[0].slice(-12).toLowerCase();
      const storeSlug = `e2e-adm-shop-${suffix}`;
      const orgSlug = `e2e-adm-biz-${suffix}`;

      await loginAsThrowawayAccount(page, throwawayAccount);
      await page.goto('/dashboard/onboarding');
      await waitForPageReady(page);
      await page.getByLabel('Business name').fill('E2E Admin Business');
      await page.getByLabel('Business address').fill(orgSlug);
      await page.getByLabel('Store name').fill('E2E Admin Shop');
      await page.getByLabel('Store address').fill(storeSlug);
      await page.getByRole('button', { name: 'Create my store' }).click();
      await expect(page).toHaveURL(/\/dashboard\/onboarding\/status\/[A-Za-z0-9_-]+$/);

      // Same page, now signed in as the admin.
      await page.context().clearCookies();
      await signInWithSavedSession(page.context(), 'admin');

      await searchStores(page, storeSlug);
      const storeRow = page.getByRole('row').filter({ hasText: storeSlug });
      await expect(storeRow.getByText('E2E Admin Business')).toBeVisible();
      await expect(storeRow.getByText('Provisioning', { exact: true })).toBeVisible();
      await expect(storeRow.getByText('No actions')).toBeVisible();
      await expect(storeRow.getByRole('button')).toHaveCount(0);

      await page.goto(`/admin/organizations?q=${encodeURIComponent(orgSlug)}`);
      await waitForPageReady(page);
      const orgRow = page.getByRole('row').filter({ hasText: orgSlug });
      await expect(orgRow.getByRole('cell', { name: '1', exact: true })).toBeVisible();

      await orgRow.getByRole('link', { name: /^view stores of/i }).click();
      await expect(page).toHaveURL(/\/admin\/stores\?org=/);
      await waitForPageReady(page);
      await expect(page.getByText(storeSlug)).toBeVisible();
      await expect(page.getByRole('link', { name: 'Show all stores' })).toBeVisible();
    });
  });

  test.describe('as a regular user', () => {
    test.use({ storageState: STORAGE_STATE.user });

    test('is sent back to the dashboard', async ({ page }) => {
      test.skip(!process.env.TEST_USER_EMAIL, 'Skipped: TEST_USER_EMAIL not configured');

      for (const path of ['/admin/stores', '/admin/organizations']) {
        await page.goto(path);
        await expect(page).toHaveURL(/\/dashboard/);
      }
    });
  });
});
