import { test, expect } from '@playwright/test';

/**
 * KAN-64: wildcard subdomain routing, on `*.localhost`.
 *
 * Needs a backend whose platform database holds these stores (the PR description lists the seed):
 *   e2e-live       ACTIVE     "E2E Live Shop"
 *   e2e-suspended  SUSPENDED
 * Chromium resolves `*.localhost` to loopback, so no hosts-file entry is needed.
 */
const APP_ORIGIN = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:3000');
const storeUrl = (slug: string, path = '/') =>
  `${APP_ORIGIN.protocol}//${slug}.localhost:${APP_ORIGIN.port}${path}`;

test.describe('store subdomains', () => {
  test('an active store renders its public name on its subdomain', async ({ page }) => {
    const response = await page.goto(storeUrl('e2e-live'));

    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'E2E Live Shop' })).toBeVisible();
    await expect(page).toHaveTitle(/E2E Live Shop/);
  });

  test('an unknown store is a 404', async ({ page }) => {
    const response = await page.goto(storeUrl('e2e-ghost'));
    expect(response?.status()).toBe(404);
  });

  test('a suspended store is a 404 identical to an unknown one', async ({ page }) => {
    const suspended = await page.goto(storeUrl('e2e-suspended'));
    const suspendedBody = await page.content();
    const unknown = await page.goto(storeUrl('e2e-ghost'));

    expect(suspended?.status()).toBe(404);
    expect(unknown?.status()).toBe(404);
    expect(suspendedBody).not.toContain('e2e-suspended');
  });

  test('root-domain routes are not reachable from a store host', async ({ page }) => {
    for (const path of ['/dashboard', '/admin', '/login']) {
      const response = await page.goto(storeUrl('e2e-live', path));
      expect(response?.status(), path).toBe(404);
      expect(new URL(page.url()).pathname, path).toBe(path);
    }
  });

  test('reserved names are the platform, not a store', async ({ page }) => {
    const response = await page.goto(storeUrl('www'));
    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'E2E Live Shop' })).toHaveCount(0);
  });

  test('the internal storefront route is not reachable on the root domain', async ({ page }) => {
    const response = await page.goto(`${APP_ORIGIN.origin}/storefront/e2e-live`);
    expect(response?.status()).toBe(404);
  });

  test('the root domain still serves the normal app', async ({ page }) => {
    const response = await page.goto(APP_ORIGIN.origin);
    expect(response?.status()).toBe(200);
    const protectedResponse = await page.goto(`${APP_ORIGIN.origin}/dashboard`);
    expect(new URL(page.url()).pathname).toBe('/login');
    expect(protectedResponse?.status()).toBeLessThan(400);
  });
});
