import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';

/**
 * KAN-73: merchant product screens (list with filters, create, editor with variants, images and categories).
 *
 * Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and E2E_BACKEND_DIR, the path of the
 * fastapi_backend folder. Without QStash a new store stays PROVISIONING, and product writes need an ACTIVE store,
 * so the spec runs the real provisioning steps inline through helpers/activate_store.py (uv, same environment as
 * the backend). See docs/developer/local-e2e.md.
 */

const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const ACTIVATE_SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'helpers',
  'activate_store.py'
);

function backendHeaders(sessionToken: string): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Internal-Key': process.env.BACKEND_INTERNAL_KEY ?? '',
    'X-Session-Token': sessionToken,
  };
}

/** Creates an organisation and an ACTIVE store for the signed-in throwaway account. */
async function seedActiveStore(page: Page, suffix: string): Promise<void> {
  const session = (await page.context().cookies()).find((cookie) => cookie.name === 'session');
  if (!session || !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR) {
    throw new Error('Seeding needs the session cookie, BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR');
  }
  const backendUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
  const headers = backendHeaders(session.value);
  const slug = `e2e-prod-${suffix}`.toLowerCase().replace(/[^a-z0-9-]/g, '-');

  const org = await fetch(`${backendUrl}/v1/organizations`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: 'Products org', slug }),
  });
  if (!org.ok) throw new Error(`Creating the organisation failed (HTTP ${org.status})`);
  const organizationId = ((await org.json()) as { data: { id: string } }).data.id;

  const store = await fetch(`${backendUrl}/v1/organizations/${organizationId}/stores`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: 'Products store', slug: `${slug}-shop` }),
  });
  if (!store.ok) throw new Error(`Creating the store failed (HTTP ${store.status})`);
  const storeId = ((await store.json()) as { data: { id: string } }).data.id;

  execFileSync('uv', ['run', 'python', ACTIVATE_SCRIPT, storeId], {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  });
}

async function createSimpleProduct(
  page: Page,
  input: { title: string; sku: string; price: string }
): Promise<void> {
  await page.goto('/dashboard/products/new');
  await waitForPageReady(page);
  await page.getByLabel('Title').fill(input.title);
  await page.getByLabel('SKU').fill(input.sku);
  await page.getByLabel(/^Price \(/).fill(input.price);
  await page.getByRole('button', { name: 'Create product' }).click();
  await expect(page.getByRole('heading', { level: 1, name: input.title })).toBeVisible();
}

test.describe('Merchant product management', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(240_000);

  test('validates, creates, lists and filters products', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));

    // Empty store: an empty state and the way to add a product.
    await page.goto('/dashboard/products');
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Products' })).toBeVisible();
    await expect(page.getByTestId('no-products')).toContainText('No products yet.');

    // Validation: an empty form is refused before the server.
    await page.getByRole('link', { name: 'New product' }).click();
    await waitForPageReady(page);
    await page.getByRole('button', { name: 'Create product' }).click();
    await expect(page.getByText('Title is required')).toBeVisible();
    await expect(page.getByText('Enter a price like 12.50')).toBeVisible();

    // Create two products.
    await createSimpleProduct(page, { title: 'Blue Tee', sku: 'E2E-TEE', price: '12.50' });
    await createSimpleProduct(page, { title: 'Red Mug', sku: 'E2E-MUG', price: '8' });

    // A duplicate SKU shows the backend's curated message and keeps the form.
    await page.goto('/dashboard/products/new');
    await waitForPageReady(page);
    await page.getByLabel('Title').fill('Another Tee');
    await page.getByLabel('SKU').fill('e2e-tee');
    await page.getByLabel(/^Price \(/).fill('9');
    await page.getByRole('button', { name: 'Create product' }).click();
    await expect(page.getByRole('form', { name: 'New product' }).getByRole('alert')).toContainText(
      /sku/i
    );

    // List: both rows, the page filter is labelled as page-only, and the status filter is applied by the server.
    await page.goto('/dashboard/products');
    await waitForPageReady(page);
    await expect(page.getByTestId('product-row')).toHaveCount(2);
    await expect(page.getByText(/store-wide search is not available yet/i)).toBeVisible();
    await page.getByLabel('Filter this page by title').fill('mug');
    await expect(page.getByTestId('product-row')).toHaveCount(1);
    await page.getByLabel('Filter this page by title').fill('');
    await page.getByLabel('Status').selectOption('active');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('no-products')).toContainText('No products match these filters.');
  });

  // A second test with its own account: the backend rate-limits each account (100 calls a minute), and every
  // page load costs several calls.
  test('edits variants and details, shows the documented gaps, and deletes a product', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));
    await createSimpleProduct(page, { title: 'Blue Tee', sku: 'E2E-TEE', price: '12.50' });
    await waitForPageReady(page);

    // Editor: publish, change the price, and see both persist after a reload.
    await page.getByLabel('Status').selectOption('active');
    await page.getByRole('button', { name: 'Save details' }).click();
    await expect(page.getByText('Product saved.')).toBeVisible();

    const row = page.getByTestId('variant-row').first();
    await row.getByLabel(/^Price \(/).fill('19.99');
    await row.getByRole('button', { name: 'Save variant' }).click();
    await expect(row.getByText('Variant saved.')).toBeVisible();
    await page.reload();
    await waitForPageReady(page);
    await expect(
      page
        .getByTestId('variant-row')
        .first()
        .getByLabel(/^Price \(/)
    ).toHaveValue('19.99');
    await expect(page.getByLabel('Status')).toHaveValue('active');

    // The last variant cannot be removed: the backend's message is shown.
    await page.getByRole('button', { name: 'Delete variant' }).click();
    await page.getByRole('button', { name: 'Confirm delete variant' }).click();
    await expect(
      page.getByRole('alert').filter({ hasText: /at least one variant/i })
    ).toBeVisible();

    // Images and categories: documented gaps, no upload control, categories by id only.
    await expect(page.getByTestId('no-images')).toBeVisible();
    await expect(page.getByText(/uploading new images .* is not available yet/i)).toBeVisible();
    await expect(page.locator('input[type="file"]')).toHaveCount(0);
    await expect(page.getByTestId('categories-field')).toContainText('categories show by id');

    // Delete returns to the list, which no longer has the product.
    await page.getByRole('button', { name: 'Delete product' }).click();
    await page.getByRole('button', { name: 'Confirm delete product' }).click();
    await expect(page).toHaveURL(/\/dashboard\/products$/);
    await waitForPageReady(page);
    await expect(page.getByRole('link', { name: 'Blue Tee' })).toHaveCount(0);
    await expect(page.getByTestId('no-products')).toBeVisible();
  });

  test('creates a product with options and one variant per combination', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));

    await page.goto('/dashboard/products/new');
    await waitForPageReady(page);
    await page.getByLabel('Title').fill('Sized Tee');
    await page.getByRole('button', { name: 'Add option' }).click();
    await page.getByLabel('Option 1 name').fill('Size');
    await page.getByLabel('Option 1 values').fill('S, M');

    const rows = page.getByTestId('variant-row');
    await expect(rows).toHaveCount(2);
    for (const [index, sku, price] of [
      [0, 'E2E-S', '10'],
      [1, 'E2E-M', '12'],
    ] as const) {
      await rows.nth(index).getByLabel('SKU').fill(sku);
      await rows
        .nth(index)
        .getByLabel(/^Price \(/)
        .fill(price);
    }
    await page.getByRole('button', { name: 'Create product' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Sized Tee' })).toBeVisible();
    await expect(page.getByTestId('variant-row')).toHaveCount(2);

    // The list shows the price range across variants.
    await page.goto('/dashboard/products');
    await waitForPageReady(page);
    await expect(page.getByTestId('product-row')).toContainText('–');
  });
});
