import { test, expect } from '@playwright/test';

/**
 * KAN-202: preview-only `/s/{slug}` access. Temporary: delete with the route once the wildcard domain exists.
 *
 * Run with the flag on (the flag-off and production cases are unit-tested in proxy-path-preview.test.ts):
 *   STOREFRONT_PATH_PREVIEW=true npm run test:e2e:local -- src/__tests__/e2e/storefront-path-preview.spec.ts
 * Uses the same backend seed as storefront-subdomain.spec.ts:
 *   e2e-live       ACTIVE     "E2E Live Shop"
 *   e2e-suspended  SUSPENDED
 */
const APP_ORIGIN = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:3000');
const previewUrl = (path: string) => `${APP_ORIGIN.origin}${path}`;
const hostStoreUrl = (slug: string) =>
  `${APP_ORIGIN.protocol}//${slug}.localhost:${APP_ORIGIN.port}/`;

test.describe('storefront path preview', () => {
  test.skip(
    process.env.STOREFRONT_PATH_PREVIEW !== 'true',
    'needs STOREFRONT_PATH_PREVIEW=true on the server under test'
  );

  test('an active store renders on /s/{slug} and is noindex', async ({ page }) => {
    const response = await page.goto(previewUrl('/s/e2e-live'));

    expect(response?.status()).toBe(200);
    expect(response?.headers()['x-robots-tag']).toBe('noindex');
    await expect(page.getByRole('heading', { name: 'E2E Live Shop' })).toBeVisible();
  });

  test('unknown, suspended, reserved and malformed slugs share one 404 body', async ({ page }) => {
    const ghost = await page.goto(previewUrl('/s/e2e-ghost'));
    const ghostBody = await page.content();
    expect(ghost?.status()).toBe(404);
    expect(ghost?.headers()['x-robots-tag']).toBe('noindex');

    for (const slug of ['e2e-suspended', 'www', 'admin', 'ab', 'Bad_Slug', 'E2E-LIVE']) {
      const response = await page.goto(previewUrl(`/s/${slug}`));
      expect(response?.status(), slug).toBe(404);
      expect(response?.headers()['x-robots-tag'], slug).toBe('noindex');
      expect(await page.content(), slug).toBe(ghostBody);
    }

    const missing = await page.goto(previewUrl('/s'));
    expect(missing?.status()).toBe(404);
    expect(await page.content()).toBe(ghostBody);
  });

  test('the 404 body matches host routing', async ({ page }) => {
    await page.goto(previewUrl('/s/e2e-ghost'));
    const pathBody = await page.content();
    await page.goto(hostStoreUrl('e2e-ghost'));
    expect(await page.content()).toBe(pathBody);
  });

  test('direct /storefront/{slug} is still a 404, even with a forged slug header', async ({
    request,
  }) => {
    const plain = await request.get(previewUrl('/storefront/e2e-live'));
    expect(plain.status()).toBe(404);

    const forged = await request.get(previewUrl('/storefront/e2e-live'), {
      headers: { 'x-storefront-slug': 'e2e-live' },
    });
    expect(forged.status()).toBe(404);
  });

  test('a forged slug header cannot turn another slug into a live store', async ({ request }) => {
    const forged = await request.get(previewUrl('/s/e2e-ghost'), {
      headers: { 'x-storefront-slug': 'e2e-live' },
    });
    expect(forged.status()).toBe(404);
    expect(await forged.text()).not.toContain('E2E Live Shop');
  });

  test('the normal app is unaffected and carries no noindex header', async ({ request }) => {
    const response = await request.get(previewUrl('/'));
    expect(response.status()).toBe(200);
    expect(response.headers()['x-robots-tag']).toBeUndefined();
  });
});
