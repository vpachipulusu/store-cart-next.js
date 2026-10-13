import type { Page } from '@playwright/test';

import { test, expect } from './helpers/fixtures';
import {
  expectRedirectToLogin,
  expectToast,
  loginAsThrowawayAccount,
  useDistinctClientIp,
  waitForHydration,
  waitForPageReady,
} from './helpers/e2e-utils';

async function logOut(page: Page): Promise<void> {
  await waitForPageReady(page);
  // The legacy avatar trigger has no accessible label; scope its menu to the header.
  await page.locator('header button.rounded-full[aria-haspopup="menu"]').click();
  await page.getByRole('menuitem', { name: 'Log out', exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function openProfile(page: Page): Promise<void> {
  await page.goto('/dashboard/profile');
  await waitForPageReady(page);
  await expect(page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save Changes', exact: true })).toBeEnabled();
}

test.describe('Legacy browser account lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    await useDistinctClientIp(page);
  });
  test('fresh sign-in survives reload and a protected-page navigation', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.reload();
    await waitForPageReady(page);
    await expect(page).toHaveURL(/\/dashboard$/);
    await openProfile(page);
    await page.reload();
    await expect(page.getByLabel('Display Name', { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard\/profile$/);
  });

  test('logging out denies later protected-page visits', async ({ page, throwawayAccount }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await logOut(page);
    await expectRedirectToLogin(page, '/dashboard/profile');
    await expectRedirectToLogin(page, '/dashboard/security');
  });

  test('editing one profile field persists without clearing other saved fields', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await openProfile(page);
    const profile = {
      'Display Name': 'Lifecycle Merchant',
      Bio: 'Initial account biography',
      Location: 'London, UK',
      Website: 'https://example.com/lifecycle',
      'Phone Number': '+442079460001',
    };
    for (const [label, value] of Object.entries(profile)) {
      await page.getByLabel(label, { exact: true }).fill(value);
    }
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await expectToast(page, 'Profile updated successfully');
    await page.reload();
    await waitForPageReady(page);
    for (const [label, value] of Object.entries(profile)) {
      await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);
    }

    await page.getByLabel('Bio', { exact: true }).fill('Updated account biography');
    await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
    await expectToast(page, 'Profile updated successfully');
    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByLabel('Bio', { exact: true })).toHaveValue('Updated account biography');
    for (const [label, value] of Object.entries(profile).filter(([label]) => label !== 'Bio')) {
      await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);
    }
  });

  test('another fresh sign-in adds a successful login-history entry', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    const history = page.getByRole('table').filter({
      has: page.getByRole('columnheader', { name: 'Date & Time', exact: true }),
    });
    const rows = history.locator('tbody tr');
    await expect.poll(() => rows.count()).toBeGreaterThan(0);
    const beforeLogin = await rows.count();
    await expect(
      history.locator('tbody tr').first().getByText('Success', { exact: true })
    ).toBeVisible();
    await logOut(page);
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    // Legacy token-refresh subscriptions also record history; one login can add multiple rows.
    await expect.poll(() => rows.count()).toBeGreaterThan(beforeLogin);
    const afterLogin = await rows.count();
    await expect(rows.getByText('Success', { exact: true })).toHaveCount(afterLogin);
    await page.reload();
    await waitForPageReady(page);
    await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(afterLogin);
    await expect(rows.getByText('Failed', { exact: true })).toHaveCount(0);
  });

  test('account deletion requires confirmation and then denies protected access', async ({
    page,
    throwawayAccount,
    expectThrowawayAccountDeleted,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await page.goto('/dashboard/security');
    await waitForPageReady(page);
    await page.getByRole('button', { name: 'Delete Account', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete Account', exact: true });
    const confirm = dialog.getByRole('button', { name: 'Delete Account', exact: true });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Type DELETE to confirm', { exact: true }).fill('delete');
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel('Type DELETE to confirm', { exact: true }).fill('DELETE');
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(page).toHaveURL(/\/$/);
    await expectRedirectToLogin(page, '/dashboard/profile');
    await expectRedirectToLogin(page, '/dashboard/security');
    await page.goto('/login');
    await waitForHydration(page);
    await page.getByLabel('Email', { exact: true }).fill(throwawayAccount.email);
    await page.getByLabel('Password', { exact: true }).fill(throwawayAccount.password);
    await page.getByRole('button', { name: 'Sign In', exact: true }).click();
    await expect(
      page.getByText('Invalid email or password. Please try again.', { exact: true })
    ).toBeVisible();
    await expect(page).toHaveURL(/\/login(?:\?|$)/);
    await expectThrowawayAccountDeleted(throwawayAccount);
  });
});
