import type { Page } from '@playwright/test';
import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';
import {
  BACKEND_DIR,
  createSimpleProduct,
  createSizedProduct,
  RATE_WINDOW_MS,
  seedActiveStore,
} from './helpers/products-e2e';

/**
 * KAN-73: merchant product screens (list with search and filters, create, editor with variants, images and
 * categories). Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and E2E_BACKEND_DIR. See
 * helpers/products-e2e.ts and docs/developer/local-e2e.md.
 */

const STORAGE_HOST = '**/*.r2.cloudflarestorage.com/**';
const STORAGE_CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'PUT, GET, OPTIONS',
  'access-control-allow-headers': 'content-type',
};
// 1x1 transparent PNG.
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64'
);

/** Validation, a storage/CORS failure, then a successful direct upload that is registered and persists. */
async function exerciseImageUpload(page: Page): Promise<void> {
  const fileInput = page.getByLabel('Image file');
  const addButton = page.getByRole('button', { name: 'Add image' });
  const form = page.getByRole('form', { name: 'Add image' });

  await fileInput.setInputFiles({
    name: 'notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('x'),
  });
  await expect(form.getByRole('alert')).toContainText('Choose a JPEG, PNG or WebP image.');
  await expect(addButton).toBeDisabled();

  await fileInput.setInputFiles({
    name: 'huge.png',
    mimeType: 'image/png',
    buffer: Buffer.alloc(10 * 1024 * 1024 + 1),
  });
  await expect(form.getByRole('alert')).toContainText('larger than 10 MB');

  // Storage unreachable (or blocking the site by CORS): one clear alert, nothing registered.
  await page.route(STORAGE_HOST, (route) => route.abort('failed'));
  await fileInput.setInputFiles({ name: 'tee.png', mimeType: 'image/png', buffer: TINY_PNG });
  await addButton.click();
  await expect(form.getByRole('alert')).toContainText('could not reach storage');
  await expect(page.getByTestId('image-row')).toHaveCount(0);
  await page.unroute(STORAGE_HOST);

  // Storage accepts the PUT: progress is shown, the image is registered and survives a reload.
  const puts: string[] = [];
  await page.route(STORAGE_HOST, (route) => {
    const request = route.request();
    if (request.method() === 'PUT') puts.push(request.headers()['content-type'] ?? '');
    return route.fulfill({ status: request.method() === 'PUT' ? 200 : 204, headers: STORAGE_CORS });
  });
  await page.getByLabel('Alt text (optional)').fill('Blue tee front');
  await fileInput.setInputFiles({ name: 'tee.png', mimeType: 'image/png', buffer: TINY_PNG });
  await addButton.click();
  const row = page.getByTestId('image-row');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('Blue tee front');
  await expect(row).toContainText(/stores\/.+\.png/);
  expect(puts).toEqual(['image/png']);
  await page.unroute(STORAGE_HOST);

  await page.reload();
  await waitForPageReady(page);
  await expect(page.getByTestId('image-row')).toHaveCount(1);
}

test.describe('Merchant product management', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(480_000);

  test('validates, creates, lists, filters, edits and deletes products', async ({
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

    // Pause so one account stays under the backend's 100 calls a minute.
    await page.waitForTimeout(RATE_WINDOW_MS);
    await createSizedProduct(page);

    await page.waitForTimeout(RATE_WINDOW_MS);
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
    await expect(page.getByTestId('product-row')).toHaveCount(3);
    await expect(page.getByTestId('product-row').filter({ hasText: 'Sized Tee' })).toContainText(
      '–'
    );
    // Server-side search by title, then by SKU (case-insensitive), then a search with no match.
    await page.getByLabel('Search by title or SKU').fill('mug');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('product-row')).toHaveCount(1);
    await expect(page.getByRole('link', { name: 'Red Mug' })).toBeVisible();
    await page.getByLabel('Search by title or SKU').fill('E2E-TEE');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('product-row')).toHaveCount(1);
    await expect(page.getByRole('link', { name: 'Blue Tee' })).toBeVisible();
    await page.getByLabel('Search by title or SKU').fill('no-such-product');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('no-products')).toContainText('No products match these filters.');
    await page.getByRole('link', { name: 'Clear filters' }).click();
    await expect(page.getByTestId('product-row')).toHaveCount(3);
    await page.getByLabel('Category').selectOption({ label: 'All categories' });
    await page.getByLabel('Status').selectOption('active');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('no-products')).toContainText('No products match these filters.');

    // The backend rate-limits sign-in (5 per 15 minutes per address) and each account to 100 calls a minute, so the
    // editor half continues in the same signed-in session after a pause instead of using a second account.
    await page.waitForTimeout(RATE_WINDOW_MS);
    await page.goto('/dashboard/products');
    await waitForPageReady(page);
    await page.getByRole('link', { name: 'Blue Tee' }).click();
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Blue Tee' })).toBeVisible();

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

    // Images (KAN-249): the add form is offered. The upload steps need a backend that can presign (storage
    // settings on the local uvicorn, test values only) and stand in for storage with a browser-side stub.
    await expect(page.getByTestId('no-images')).toBeVisible();
    await expect(page.getByRole('form', { name: 'Add image' })).toBeVisible();
    await expect(page.getByLabel('Image file')).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Add image' })).toBeDisabled();
    if (process.env.E2E_IMAGE_UPLOAD === '1') await exerciseImageUpload(page);

    // Categories: the store has none, and the list says so.
    await expect(page.getByTestId('categories-field')).toContainText(
      'This store has no categories yet.'
    );

    // Delete returns to the list, which no longer has the product.
    await page.getByRole('button', { name: 'Delete product' }).click();
    await page.getByRole('button', { name: 'Confirm delete product' }).click();
    await expect(page).toHaveURL(/\/dashboard\/products$/);
    await waitForPageReady(page);
    await expect(page.getByRole('link', { name: 'Blue Tee' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Red Mug' })).toBeVisible();
  });
});
