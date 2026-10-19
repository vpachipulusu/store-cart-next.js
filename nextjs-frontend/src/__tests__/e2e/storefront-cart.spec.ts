import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';

/**
 * KAN-76: the server-side cart on a store host. Needs the FastAPI backend (BACKEND_API_URL,
 * BACKEND_INTERNAL_KEY) and E2E_BACKEND_DIR, like product-management.spec.ts. Seeds two ACTIVE stores
 * (no login) through helpers/seed_cart.py: each has an active mug (stock 5, price 12.50) and a draft mug.
 * Chromium resolves `*.localhost` to loopback, so the page can call the cart on its own host.
 */

const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const SEED_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'helpers/seed_cart.py');
const APP_ORIGIN = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:3000');
const storeUrl = (slug: string, route = '/') =>
  `${APP_ORIGIN.protocol}//${slug}.localhost:${APP_ORIGIN.port}${route}`;

interface SeededStore {
  slug: string;
  activeVariantId: string;
  draftVariantId: string;
}

function seedStore(slug: string): SeededStore {
  const output = execFileSync('uv', ['run', 'python', SEED_SCRIPT, slug], {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  }).toString();
  const seeded = JSON.parse(output.trim().split('\n').pop() ?? '{}') as Omit<SeededStore, 'slug'>;
  return { slug, ...seeded };
}

interface CartReply {
  status: number;
  body: { success: boolean; error?: string; data?: Record<string, unknown> };
}

/** A same-origin call from a page on the store host, so the browser handles the cookie and sends `Origin`. */
async function cart(page: Page, method: string, route: string, body?: unknown): Promise<CartReply> {
  return page.evaluate(
    async ({ method, route, body }) => {
      const response = await fetch(route, {
        method,
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return { status: response.status, body: await response.json() };
    },
    { method, route, body }
  );
}

const lines = (reply: CartReply) => reply.body.data?.lines as Array<Record<string, unknown>>;

test.describe('storefront cart', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(240_000);

  let alpha: SeededStore;
  let beta: SeededStore;

  test.beforeAll(() => {
    const run = Date.now().toString(36);
    alpha = seedStore(`e2e-cart-a-${run}`);
    beta = seedStore(`e2e-cart-b-${run}`);
  });

  test('keeps a priced cart in a store-scoped httpOnly cookie and re-checks stock', async ({
    page,
    context,
  }) => {
    await page.goto(storeUrl(alpha.slug));

    const empty = await cart(page, 'GET', '/cart');
    expect(empty.status).toBe(200);
    expect(lines(empty)).toEqual([]);
    expect(empty.body.data?.can_checkout).toBe(false);
    expect(await context.cookies()).toEqual([]);

    const added = await cart(page, 'POST', '/cart/items', {
      variantId: alpha.activeVariantId,
      quantity: 2,
    });
    expect(added.status).toBe(200);
    expect(lines(added)[0]).toMatchObject({ quantity: 2, unit_price_minor: 1250, status: 'ok' });
    expect(added.body.data).toMatchObject({ subtotal_minor: 2500, can_checkout: true });
    expect(added.body.data).not.toHaveProperty('cart_token');

    const cookie = (await context.cookies()).find((c) => c.name === `sc_cart_${alpha.slug}`);
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Lax', path: '/' });
    expect(await page.evaluate(() => document.cookie)).not.toContain('sc_cart_');

    await page.reload();
    const again = await cart(page, 'GET', '/cart');
    expect(lines(again)[0]).toMatchObject({ quantity: 2 });

    const tooMany = await cart(page, 'PUT', `/cart/items/${alpha.activeVariantId}`, {
      quantity: 9,
    });
    expect(tooMany.status).toBe(409);
    expect(tooMany.body.error).toBe('Only 5 in stock');

    const changed = await cart(page, 'PUT', `/cart/items/${alpha.activeVariantId}`, {
      quantity: 4,
    });
    expect(changed.body.data).toMatchObject({ subtotal_minor: 5000 });

    const removed = await cart(page, 'DELETE', `/cart/items/${alpha.activeVariantId}`);
    expect(removed.status).toBe(200);
    expect(lines(removed)).toEqual([]);
  });

  test('refuses invalid input and items that cannot be sold', async ({ page }) => {
    await page.goto(storeUrl(alpha.slug));

    const zero = await cart(page, 'POST', '/cart/items', {
      variantId: alpha.activeVariantId,
      quantity: 0,
    });
    const draft = await cart(page, 'POST', '/cart/items', {
      variantId: alpha.draftVariantId,
      quantity: 1,
    });
    const unknown = await cart(page, 'POST', '/cart/items', {
      variantId: 'no-such-variant',
      quantity: 1,
    });

    expect(zero.status).toBe(422);
    expect(draft.status).toBe(404);
    expect(unknown.status).toBe(404);
    expect(draft.body).toEqual(unknown.body);
  });

  test('one store cart is nothing in another store', async ({ page, context }) => {
    await page.goto(storeUrl(alpha.slug));
    await cart(page, 'POST', '/cart/items', { variantId: alpha.activeVariantId, quantity: 1 });

    await page.goto(storeUrl(beta.slug));
    const other = await cart(page, 'GET', '/cart');
    const foreignVariant = await cart(page, 'POST', '/cart/items', {
      variantId: alpha.activeVariantId,
      quantity: 1,
    });

    expect(lines(other)).toEqual([]);
    expect(foreignVariant.status).toBe(404);
    const names = (await context.cookies()).map((c) => c.name);
    expect(names).toContain(`sc_cart_${alpha.slug}`);
    expect(names).not.toContain(`sc_cart_${beta.slug}`);
  });

  test('the cart is not reachable on the root domain or for an unknown store', async ({
    page,
    request,
  }) => {
    const direct = await request.get(`${APP_ORIGIN.origin}/storefront/${alpha.slug}/cart`);
    expect(direct.status()).toBe(404);

    const ghost = await page.goto(storeUrl('e2e-cart-ghost', '/cart'));
    expect(ghost?.status()).toBe(404);
  });
});
