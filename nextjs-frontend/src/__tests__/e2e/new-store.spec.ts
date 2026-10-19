import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-254: a merchant creates another store from the dashboard store menu, follows its setup, lands on it once it
 * is ready and can switch back; on the Free plan the menu shows the upgrade message instead.
 *
 * Needs the FastAPI backend (BACKEND_API_URL), BACKEND_INTERNAL_KEY, and E2E_BACKEND_DIR (the fastapi_backend
 * folder, run with the same environment as uvicorn). Without QStash a new store stays PROVISIONING, so the spec
 * runs the real provisioning steps inline (activate_store.py) and sets the Pro tier the Stripe webhook would set
 * (set_org_tier.py).
 */

const HELPERS = path.join(path.dirname(fileURLToPath(import.meta.url)), 'helpers');
const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const FREE_LIMIT_MESSAGE = 'The Free plan allows 1 store. Upgrade your plan to add more.';
/** Status polling backs off from 2s; the inline provisioning run takes a few seconds more. */
const READY_TIMEOUT_MS = 90_000;

type Seeded = { organizationId: string; storeName: string };

function backendUrl(): string {
  return (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
}

async function backendHeaders(page: Page): Promise<Record<string, string>> {
  const session = (await page.context().cookies()).find((cookie) => cookie.name === 'session');
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  if (!session || !internalKey) {
    throw new Error('Seeding needs the session cookie and BACKEND_INTERNAL_KEY');
  }
  return {
    'Content-Type': 'application/json',
    'X-Internal-Key': internalKey,
    'X-Session-Token': session.value,
  };
}

/** The throwaway account's business and first store, created through the real API. */
async function seedFirstStore(page: Page, suffix: string): Promise<Seeded> {
  const headers = await backendHeaders(page);
  const slug = `e2e-ns-${suffix}`.toLowerCase().replace(/[^a-z0-9-]/g, '-');
  const org = await fetch(`${backendUrl()}/v1/organizations`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: 'New store org', slug }),
  });
  if (!org.ok) throw new Error(`Creating the organisation failed (HTTP ${org.status})`);
  const organizationId = ((await org.json()) as { data: { id: string } }).data.id;
  const storeName = `First ${suffix}`;
  const store = await fetch(`${backendUrl()}/v1/organizations/${organizationId}/stores`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: storeName, slug: `${slug}-first` }),
  });
  if (!store.ok) throw new Error(`Creating the first store failed (HTTP ${store.status})`);
  return { organizationId, storeName };
}

async function storeIdBySlug(page: Page, organizationId: string, slug: string): Promise<string> {
  const response = await fetch(`${backendUrl()}/v1/organizations/${organizationId}/stores`, {
    headers: await backendHeaders(page),
  });
  if (!response.ok) throw new Error(`Listing stores failed (HTTP ${response.status})`);
  const stores = ((await response.json()) as { data: Array<{ id: string; slug: string }> }).data;
  const match = stores.find((store) => store.slug === slug);
  if (!match) throw new Error(`No store with slug ${slug}`);
  return match.id;
}

function runBackendHelper(script: string, args: string[]): void {
  if (!BACKEND_DIR) throw new Error('E2E_BACKEND_DIR is not set');
  execFileSync('uv', ['run', 'python', path.join(HELPERS, script), ...args], {
    cwd: BACKEND_DIR,
    // The helper needs the backend settings the developer exported for uvicorn; frontend code must not name them.
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  });
}

/** The sidebar and header each mount a switcher; CSS shows one per width, so only the visible one counts. */
function storeMenuTrigger(page: Page) {
  return page.locator('[data-testid="store-switcher"]:visible');
}

async function openNewStoreDialog(page: Page) {
  await storeMenuTrigger(page).click();
  await page.getByRole('menuitem', { name: 'New store' }).click();
  const dialog = page.getByRole('dialog', { name: 'New store' });
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe('New store from the dashboard', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY / BACKEND_API_URL / E2E_BACKEND_DIR not set (needs FastAPI)'
  );

  test('on the Free plan the menu offers New store and shows the upgrade message', async ({
    page,
    throwawayAccount,
  }) => {
    const suffix = throwawayAccount.email.split('@')[0].slice(-12);
    await loginAsThrowawayAccount(page, throwawayAccount);
    const first = await seedFirstStore(page, suffix);

    await page.goto('/dashboard');
    await waitForPageReady(page);
    await expect(storeMenuTrigger(page)).toContainText(first.storeName);

    const dialog = await openNewStoreDialog(page);
    await dialog.getByLabel('Store name').fill(`Second ${suffix}`);
    await dialog.getByRole('button', { name: 'Create store' }).click();

    await expect(dialog.getByTestId('store-limit')).toContainText(FREE_LIMIT_MESSAGE);
    await expect(dialog.getByRole('link', { name: 'See plans' })).toHaveAttribute(
      'href',
      '/pricing'
    );

    // Closing hands focus back to the menu trigger and leaves the page usable (no stuck pointer-events).
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(storeMenuTrigger(page)).toBeFocused();
    await storeMenuTrigger(page).click();
    await expect(page.getByRole('menuitemradio')).toHaveCount(1);
  });

  test('on Pro a merchant creates a second store, lands on it when ready and switches back', async ({
    page,
    throwawayAccount,
  }) => {
    test.setTimeout(180_000);
    const suffix = throwawayAccount.email.split('@')[0].slice(-12);
    await loginAsThrowawayAccount(page, throwawayAccount);
    const first = await seedFirstStore(page, suffix);
    runBackendHelper('set_org_tier.py', [first.organizationId, 'pro']);

    await page.goto('/dashboard');
    await waitForPageReady(page);
    const dialog = await openNewStoreDialog(page);

    // A taken address is reported on its field.
    const secondName = `Second ${suffix}`;
    const secondSlug = `e2e-ns-${suffix}-second`.toLowerCase().replace(/[^a-z0-9-]/g, '-');
    await dialog.getByLabel('Store name').fill(secondName);
    await dialog.getByLabel('Store address').fill(`e2e-ns-${suffix}-first`.toLowerCase());
    await dialog.getByRole('button', { name: 'Create store' }).click();
    await expect(dialog.getByText('That address is already taken. Choose another.')).toBeVisible();

    await dialog.getByLabel('Store address').fill(secondSlug);
    await dialog.getByRole('button', { name: 'Create store' }).click();
    await expect(dialog.getByText('We are setting up your store')).toBeVisible();

    // Finish provisioning the way the job would; the dialog sees ACTIVE, selects the store and closes.
    runBackendHelper('activate_store.py', [
      await storeIdBySlug(page, first.organizationId, secondSlug),
    ]);
    await expect(dialog).toHaveCount(0, { timeout: READY_TIMEOUT_MS });
    await expect(storeMenuTrigger(page)).toContainText(secondName);

    // Both stores are listed and switching back works, and survives a reload.
    await storeMenuTrigger(page).click();
    await expect(page.getByRole('menuitemradio')).toHaveCount(2);
    await page.getByRole('menuitemradio', { name: new RegExp(first.storeName) }).click();
    await expect(storeMenuTrigger(page)).toContainText(first.storeName);
    await page.reload();
    await waitForPageReady(page);
    await expect(storeMenuTrigger(page)).toContainText(first.storeName);
  });
});
