import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-60: a verified user with no store is sent to onboarding, creates a business and first store, and lands on a
 * status screen that shows the store as "setting up".
 *
 * KAN-191 adds the end states, driven by the real provisioning job (KAN-56). This spec never edits the database to
 * flip a store's status. What the store ends as depends on how the backend under test is configured, which the
 * spec cannot see, so E2E_PROVISIONING says which backend this run uses:
 *
 *   unset    no QStash configured (the local default): the job never runs, the store stays "setting up".
 *   ready    QStash configured and reachable from the internet (PROVISIONING_BASE_URL is a public https origin of
 *            this backend): the job runs and the store becomes ACTIVE.
 *   failed   QStash configured with a token that QStash refuses: the job cannot be enqueued and the store is
 *            created FAILED (see the createStore docs in the API).
 *
 * Needs the FastAPI backend (BACKEND_API_URL) and BACKEND_INTERNAL_KEY in the environment.
 */

const STATUS_URL = /\/dashboard\/onboarding\/status\/[A-Za-z0-9_-]+$/;
const PROVISIONING_MODES = ['unset', 'ready', 'failed'] as const;
const PROVISIONING_MODE = process.env.E2E_PROVISIONING ?? 'unset';
if (!PROVISIONING_MODES.some((mode) => mode === PROVISIONING_MODE)) {
  // A typo must not silently skip every test in this file.
  throw new Error(`E2E_PROVISIONING must be one of ${PROVISIONING_MODES.join(', ')}`);
}
/** The three provisioning steps run in separate QStash deliveries; allow for retries and cold starts. */
const READY_TIMEOUT_MS = 120_000;

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

  // The mode is skipped per describe, before fixtures run, so a skipped test never creates a Firebase account.
  test.describe('backend without QStash', () => {
    test.skip(
      PROVISIONING_MODE !== 'unset',
      'Needs a backend without QStash (the store stays PROVISIONING)'
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

  test.describe('backend with QStash reachable from the internet', () => {
    test.skip(
      PROVISIONING_MODE !== 'ready',
      'Needs E2E_PROVISIONING=ready (QStash reachable from the internet)'
    );

    test('takes a new merchant from sign-up to a ready store through the provisioning job', async ({
      page,
      throwawayAccount,
    }) => {
      test.setTimeout(READY_TIMEOUT_MS + 60_000);
      const suffix = throwawayAccount.email.split('@')[0].slice(-12).toLowerCase();
      await loginAsThrowawayAccount(page, throwawayAccount);

      await page.goto('/dashboard');
      await expect(page).toHaveURL(/\/dashboard\/onboarding$/);
      await waitForPageReady(page);
      await fillStoreFields(page, suffix, true);
      await page.getByRole('button', { name: 'Create my store' }).click();
      await expect(page).toHaveURL(STATUS_URL);

      // The status page polls; nothing here touches the database.
      await expect(page.getByTestId('store-status')).toContainText(/your store is ready/i, {
        timeout: READY_TIMEOUT_MS,
      });
      await expect(page.getByTestId('provisioning-pill')).toHaveText('Ready');
      await page.getByRole('link', { name: 'Open dashboard' }).click();
      await expect(page).toHaveURL(/\/dashboard$/);
      await expect(page.getByTestId('no-stores')).toHaveCount(0);
    });
  });

  test.describe('backend that cannot enqueue provisioning', () => {
    test.skip(
      PROVISIONING_MODE !== 'failed',
      'Needs E2E_PROVISIONING=failed (QStash refuses the token)'
    );

    test('shows a failed provisioning with accurate copy and a status check, not a fake retry', async ({
      page,
      throwawayAccount,
    }) => {
      test.slow();
      const suffix = throwawayAccount.email.split('@')[0].slice(-12).toLowerCase();
      await loginAsThrowawayAccount(page, throwawayAccount);

      await page.goto('/dashboard/onboarding');
      await waitForPageReady(page);
      await fillStoreFields(page, suffix, true);
      await page.getByRole('button', { name: 'Create my store' }).click();
      await expect(page).toHaveURL(STATUS_URL);

      const status = page.getByTestId('store-status');
      await expect(status).toContainText(/could not finish setting up/i);
      await expect(page.getByTestId('provisioning-pill')).toHaveText('Needs attention');
      await expect(page.getByRole('link', { name: 'Open dashboard' })).toHaveCount(0);

      // Checking again re-reads the status. Nothing re-runs the job, so it says the store is still not finished.
      await expect(status).not.toContainText(/still not finished/i);
      await page.getByRole('button', { name: 'Check again' }).click();
      await expect(status).toContainText(/still not finished/i);
      await expect(status).toContainText(/could not finish setting up/i);
      await expect(page.getByRole('button', { name: 'Check again' })).toBeVisible();
    });
  });
});
