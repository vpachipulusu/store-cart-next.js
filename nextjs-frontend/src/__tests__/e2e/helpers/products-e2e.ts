import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, type Page } from '@playwright/test';
import { waitForPageReady } from './e2e-utils';

/**
 * Seeding and creation helpers for product-management.spec.ts (KAN-73).
 *
 * Without QStash a new store stays PROVISIONING, and product writes need an ACTIVE store, so seeding runs the real
 * provisioning steps inline through activate_store.py (uv, in E2E_BACKEND_DIR, the fastapi_backend folder).
 */

/** The backend allows 100 calls a minute per account; each page load costs several. */
export const RATE_WINDOW_MS = 62_000;

export const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const ACTIVATE_SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
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
export async function seedActiveStore(page: Page, suffix: string): Promise<void> {
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
    // The helper needs the same backend settings the developer exported for uvicorn (database, store encryption
    // and so on). Frontend code must not name those, so the whole environment is inherited, not picked key by key.
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  });
}

export async function createSimpleProduct(
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

/** Options create one variant row per combination; options cannot be changed after creation. */
export async function createSizedProduct(page: Page): Promise<void> {
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
}
