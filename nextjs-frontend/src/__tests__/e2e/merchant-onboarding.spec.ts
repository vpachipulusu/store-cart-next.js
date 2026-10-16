import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-60: a verified user with no store is sent to onboarding, creates a business and first store, and lands on a
 * status screen that shows the store as "setting up".
 *
 * Nothing in the backend sets a store to ACTIVE yet (KAN-56), so the "ready" screen is covered by unit tests and by
 * the follow-up KAN-191. This spec never edits the database to fake it.
 *
 * Needs the FastAPI backend (BACKEND_API_URL) and BACKEND_INTERNAL_KEY in the environment.
 */

const STATUS_URL = /\/dashboard\/onboarding\/status\/[A-Za-z0-9_-]+$/;

async function fillStoreFields(page: Page, suffix: string, withBusiness: boolean) {
  if (withBusiness) {
    await page.getByLabel('Business name').fill('E2E Business');
    await page.getByLabel('Business address').fill(`e2e-biz-${suffix}`);
  }
  await page.getByLabel('Store name').fill('E2E Shop');
  await page.getByLabel('Store address').fill(`e2e-shop-${suffix}`);
}

async function createEmptyOrganization(page: Page, suffix: string): Promise<void> {
  const session = (await page.context().cookies()).find((cookie) => cookie.name === 'session');
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  if (!session || !internalKey) {
    throw new Error('Seeding an organisation needs the session cookie and BACKEND_INTERNAL_KEY');
  }
  const backendUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
  const response = await fetch(`${backendUrl}/v1/organizations`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Internal-Key': internalKey,
      'X-Session-Token': session.value,
    },
    body: JSON.stringify({ name: 'E2E Half Business', slug: `e2e-half-${suffix}` }),
  });
  if (!response.ok) throw new Error(`Creating the organisation failed (HTTP ${response.status})`);
}

test.describe('Merchant onboarding', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY,
    'Skipped: BACKEND_INTERNAL_KEY / BACKEND_API_URL not set (needs FastAPI)'
  );

  test('sends a user with no store through onboarding to the setting-up screen', async ({
    page,
    throwawayAccount,
  }) => {
    const suffix = throwawayAccount.email.split('@')[0].slice(-12).toLowerCase();
    await loginAsThrowawayAccount(page, throwawayAccount);

    // No store yet: /dashboard sends the user straight to onboarding, no click needed (KAN-210).
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard\/onboarding$/);
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { name: 'Set up your store' })).toBeVisible();
    // The dashboard's no-store notice does not repeat itself on the onboarding page.
    await expect(page.getByTestId('no-stores')).toHaveCount(0);

    // Invalid input is refused on the server with a message on the field.
    await fillStoreFields(page, suffix, true);
    await page.getByLabel('Store address').fill('Bad Address');
    await page.getByRole('button', { name: 'Create my store' }).click();
    await expect(page.getByText(/store address can use lowercase/i)).toBeVisible();

    // A valid submission creates the business and store and shows the status screen.
    await page.getByLabel('Store address').fill(`e2e-shop-${suffix}`);
    await page.getByRole('button', { name: 'Create my store' }).click();
    await expect(page).toHaveURL(STATUS_URL);
    await expect(page.getByTestId('store-status')).toContainText(/setting up your store/i);
    await expect(page.getByRole('link', { name: 'Open dashboard' })).toHaveCount(0);

    // The store now exists, so onboarding sends the user to the dashboard and the no-store prompt is gone.
    await page.goto('/dashboard/onboarding');
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByTestId('no-stores')).toHaveCount(0);
  });

  test('resumes a half-finished onboarding instead of creating a second business', async ({
    page,
    throwawayAccount,
  }) => {
    const suffix = throwawayAccount.email.split('@')[0].slice(-12).toLowerCase();
    await loginAsThrowawayAccount(page, throwawayAccount);
    await createEmptyOrganization(page, suffix);

    await page.goto('/dashboard/onboarding');
    await waitForPageReady(page);
    await expect(page.getByText('E2E Half Business')).toBeVisible();
    await expect(page.getByLabel('Business name')).toHaveCount(0);

    await fillStoreFields(page, suffix, false);
    await page.getByRole('button', { name: 'Create my store' }).click();
    await expect(page).toHaveURL(STATUS_URL);
    await expect(page.getByTestId('store-status')).toContainText(/setting up your store/i);
  });
});
