import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';

/**
 * KAN-77: the checkout handoff on a store host. Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and
 * E2E_BACKEND_DIR, like storefront-cart.spec.ts, and seeds a store through helpers/seed_cart.py.
 *
 * Stripe is never reached: the seeded store has no connected account, so the real backend answers 409 (covered
 * below), and the happy path stubs the same-origin `/checkout` route and Stripe's own host in the browser. The order
 * is confirmed only by the backend webhook (KAN-69, covered by the backend suite), never by these pages.
 */

const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const SEED_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'helpers/seed_cart.py');
const APP_ORIGIN = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:3000');
const storeUrl = (slug: string, route = '/') =>
  `${APP_ORIGIN.protocol}//${slug}.localhost:${APP_ORIGIN.port}${route}`;
/** Node cannot resolve `*.localhost`, so API calls go to loopback with the store host as the Host header. */
const asStore = (slug: string) => ({ Host: `${slug}.localhost:${APP_ORIGIN.port}` });
const LOOPBACK = `${APP_ORIGIN.protocol}//127.0.0.1:${APP_ORIGIN.port}`;
const STRIPE_URL = 'https://checkout.stripe.com/c/pay/cs_test_e2e_kan77';

function seedStore(slug: string): { activeVariantId: string } {
  const output = execFileSync('uv', ['run', 'python', SEED_SCRIPT, slug], {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  }).toString();
  return JSON.parse(output.trim().split('\n').pop() ?? '{}') as { activeVariantId: string };
}

/** Puts one mug in the basket through the store's own cart route, so the browser holds the httpOnly cookie. */
async function fillBasket(page: Page, slug: string, variantId: string): Promise<void> {
  await page.goto(storeUrl(slug));
  const added = await page.evaluate(async (id) => {
    const response = await fetch('/cart/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ variantId: id, quantity: 1 }),
    });
    return response.status;
  }, variantId);
  expect(added).toBe(200);
}

test.describe('storefront checkout handoff', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(240_000);

  let slug: string;
  let variantId: string;

  test.beforeAll(() => {
    slug = `e2e-checkout-${Date.now().toString(36)}`;
    variantId = seedStore(slug).activeVariantId;
  });

  test('sends the shopper to Stripe and leaves the basket alone', async ({ page }) => {
    await fillBasket(page, slug, variantId);
    let posts = 0;
    await page.route(
      (url) => url.pathname === '/checkout' && url.hostname === `${slug}.localhost`,
      async (route) => {
        if (route.request().method() !== 'POST') return route.continue();
        posts += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { checkoutUrl: STRIPE_URL } }),
        });
      }
    );
    await page.route('https://checkout.stripe.com/**', (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>Stripe stub</h1>' })
    );

    await page.goto(storeUrl(slug, '/basket'));
    await page.getByRole('button', { name: 'Checkout' }).dblclick();

    await expect(page).toHaveURL(STRIPE_URL);
    await expect(page.getByRole('heading', { name: 'Stripe stub' })).toBeVisible();
    expect(posts).toBe(1);
  });

  test('shows a clear message when the backend refuses (store has no payments set up)', async ({
    page,
  }) => {
    await fillBasket(page, slug, variantId);
    await page.goto(storeUrl(slug, '/basket'));

    await page.getByRole('button', { name: 'Checkout' }).click();

    // 409 ("not ready for checkout") or 502/503 ("unavailable") depending on what the local backend has configured.
    await expect(page.locator('p[role="alert"]')).toContainText(
      /not ready for checkout|unavailable/
    );
    await expect(page.getByRole('button', { name: 'Checkout' })).not.toHaveAttribute(
      'aria-disabled',
      'true'
    );
    expect(page.url()).toBe(storeUrl(slug, '/basket'));
  });

  test('the return pages mark nothing paid, are noindex and uncached, and keep the basket', async ({
    page,
    request,
  }) => {
    await fillBasket(page, slug, variantId);

    const success = await page.goto(storeUrl(slug, '/checkout/success?order=forged&paid=true'));
    expect(success?.status()).toBe(200);
    expect(success?.headers()['cache-control']).toContain('no-store');
    await expect(
      page.getByRole('heading', { level: 1, name: 'Thank you for your order' })
    ).toBeVisible();
    await expect(page.getByText(/confirming your order/i)).toBeVisible();
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
    await expect(page.locator('main')).not.toContainText('forged');

    const cancel = await page.goto(storeUrl(slug, '/checkout/cancel'));
    expect(cancel?.headers()['cache-control']).toContain('no-store');
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
    await page.getByRole('link', { name: 'Back to your basket' }).click();
    await expect(page).toHaveURL(storeUrl(slug, '/basket'));
    await expect(page.getByRole('button', { name: 'Checkout' })).toBeVisible();

    const direct = await request.get(`${APP_ORIGIN.origin}/storefront/${slug}/checkout/success`);
    expect(direct.status()).toBe(404);
  });

  test('checkout is a same-site POST only, on a known store', async ({ page, request }) => {
    const crossSite = await request.post(`${LOOPBACK}/checkout`, {
      headers: { ...asStore(slug), Origin: storeUrl('someone-else', '') },
    });
    expect(crossSite.status()).toBe(403);

    const ghost = await request.post(`${LOOPBACK}/checkout`, {
      headers: asStore('e2e-checkout-ghost'),
    });
    // 404 for an unknown store, or 503 when the local backend has no Stripe key (checked first): refused either way.
    expect([404, 503]).toContain(ghost.status());
    expect((await ghost.json()).success).toBe(false);

    await page.goto(storeUrl(slug));
    const emptyCart = await page.evaluate(async () => {
      const response = await fetch('/checkout', { method: 'POST' });
      return { status: response.status, body: await response.json() };
    });
    expect([409, 503]).toContain(emptyCart.status); // 503 when the local backend has no Stripe key
    expect(emptyCart.body.success).toBe(false);
  });
});
