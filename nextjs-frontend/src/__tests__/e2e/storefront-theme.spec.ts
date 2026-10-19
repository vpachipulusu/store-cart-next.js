import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';

/**
 * KAN-75: the storefront theme on a store host: home -> category -> product -> add to basket, search, SEO
 * metadata, caching and 404s. Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and
 * E2E_BACKEND_DIR, like storefront-cart.spec.ts. Seeds a fresh ACTIVE store through helpers/seed_storefront.py
 * (Kitchen > Mugs, a mug with sizes, a kettle, a draft lamp). Chromium resolves `*.localhost` to loopback.
 * Prices are matched by amount only: the currency is the platform setting (USD unless set).
 */

const BACKEND_DIR = process.env.E2E_BACKEND_DIR;
const SEED_SCRIPT = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'helpers/seed_storefront.py'
);
const APP_ORIGIN = new URL(process.env.E2E_BASE_URL ?? 'http://localhost:3000');
const storeUrl = (slug: string, route = '/') =>
  `${APP_ORIGIN.protocol}//${slug}.localhost:${APP_ORIGIN.port}${route}`;

interface SeededStore {
  slug: string;
  name: string;
  mugSlug: string;
  kettleSlug: string;
  draftSlug: string;
}

function seedStore(slug: string): SeededStore {
  const output = execFileSync('uv', ['run', 'python', SEED_SCRIPT, slug], {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONPATH: BACKEND_DIR },
    stdio: 'pipe',
    timeout: 120_000,
  }).toString();
  const seeded = JSON.parse(output.trim().split('\n').pop() ?? '{}') as Omit<
    SeededStore,
    'slug' | 'name'
  >;
  // seed_cart.create_store names the store "Cart Shop {slug}".
  return { slug, name: `Cart Shop ${slug}`, ...seeded };
}

test.describe('storefront theme', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(180_000);

  let store: SeededStore;

  test.beforeAll(() => {
    store = seedStore(`e2e-theme-${Date.now().toString(36)}`);
  });

  test('home -> category -> product -> add to basket', async ({ page }) => {
    const home = await page.goto(storeUrl(store.slug));
    expect(home?.status()).toBe(200);
    await expect(page).toHaveTitle(store.name);
    await expect(page.getByRole('heading', { level: 1, name: store.name })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'New arrivals' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Copper Kettle/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Secret Desk Lamp/ })).toHaveCount(0);

    await page
      .getByRole('navigation', { name: 'Categories' })
      .getByRole('link', { name: 'Kitchen' })
      .click();
    await expect(page).toHaveURL(storeUrl(store.slug, '/categories/kitchen'));
    await expect(page.getByRole('heading', { level: 1, name: 'Kitchen' })).toBeVisible();
    await page
      .getByRole('navigation', { name: 'Kitchen subcategories' })
      .getByRole('link', { name: 'Mugs' })
      .click();

    await expect(page).toHaveURL(storeUrl(store.slug, '/categories/mugs'));
    await expect(page.getByRole('heading', { level: 1, name: 'Mugs' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('Kitchen');
    await expect(page.getByRole('link', { name: /Copper Kettle/ })).toHaveCount(0);
    await page.getByRole('link', { name: /Blue Stoneware Mug/ }).click();

    await expect(page).toHaveURL(storeUrl(store.slug, `/products/${store.mugSlug}`));
    await expect(
      page.getByRole('heading', { level: 1, name: 'Blue Stoneware Mug' })
    ).toBeVisible();
    await expect(page).toHaveTitle(`Blue Stoneware Mug | ${store.name}`);
    // The in-stock size is selected first.
    await expect(page.getByRole('radio', { name: 'Medium' })).toBeChecked();
    await expect(page.getByText(/14\.50/).first()).toBeVisible();

    await page.getByText('Small', { exact: true }).click();
    await expect(page.getByText('Out of stock')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add to basket' })).toBeDisabled();

    await page.getByText('Medium', { exact: true }).click();
    await page.getByLabel('Quantity').fill('2');
    await page.getByRole('button', { name: 'Add to basket' }).click();
    await expect(page.getByText('Added to your basket.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Basket, 2 items' })).toBeVisible();

    await page.getByRole('link', { name: 'View basket' }).click();
    await expect(page).toHaveURL(storeUrl(store.slug, '/basket'));
    await expect(page.getByRole('link', { name: 'Blue Stoneware Mug' })).toBeVisible();
    await expect(page.getByLabel('Quantity of Blue Stoneware Mug')).toHaveValue('2');
    await expect(page.getByText(/29\.00/).first()).toBeVisible();
  });

  test('search finds published titles only and is not indexed', async ({ page }) => {
    await page.goto(storeUrl(store.slug));
    await page.getByRole('searchbox', { name: 'Search products' }).first().fill('kettle');
    await page.getByRole('button', { name: 'Search' }).first().click();

    await expect(page).toHaveURL(storeUrl(store.slug, '/search?q=kettle'));
    await expect(
      page.getByRole('heading', { level: 1, name: 'Results for “kettle”' })
    ).toBeVisible();
    await expect(page.getByRole('link', { name: /Copper Kettle/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Blue Stoneware Mug/ })).toHaveCount(0);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);

    await page.goto(storeUrl(store.slug, '/search?q=Secret'));
    await expect(page.getByText('No products match your search.')).toBeVisible();
  });

  test('pages carry per-store SEO metadata', async ({ page }) => {
    await page.goto(storeUrl(store.slug, `/products/${store.mugSlug}`));

    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      'href',
      new RegExp(`^http://${store.slug}\\.localhost:\\d+/products/${store.mugSlug}$`)
    );
    await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute(
      'content',
      store.name
    );
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
      'content',
      'Blue Stoneware Mug'
    );
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      'content',
      'A heavy stoneware mug. Dishwasher safe.'
    );
    const jsonLd = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').textContent()) ?? '{}'
    ) as Record<string, unknown>;
    expect(jsonLd).toMatchObject({
      '@type': 'Product',
      name: 'Blue Stoneware Mug',
      offers: { '@type': 'AggregateOffer', lowPrice: '12.50', highPrice: '14.50' },
    });
    await expect(page.locator('meta[name="keywords"]')).toHaveCount(0);
  });

  test('catalogue pages are served from the per-store cache', async ({ request }) => {
    const url = storeUrl(store.slug, `/products/${store.kettleSlug}`);
    await request.get(url);
    const second = await request.get(url);

    expect(second.status()).toBe(200);
    expect(second.headers()['x-nextjs-cache']).toMatch(/HIT|STALE/);
  });

  test('missing products, drafts, categories and stores are 404s', async ({ request }) => {
    for (const route of [
      '/products/no-such-product',
      `/products/${store.draftSlug}`,
      '/categories/no-such-category',
      '/categories/mugs/page/9',
    ]) {
      const response = await request.get(storeUrl(store.slug, route));
      expect(response.status(), route).toBe(404);
    }
    const unknownStore = await request.get(storeUrl('e2e-theme-ghost', '/products/x'));
    expect(unknownStore.status()).toBe(404);

    const direct = await request.get(
      `${APP_ORIGIN.origin}/storefront/${store.slug}/products/${store.mugSlug}`
    );
    expect(direct.status()).toBe(404);
    expect(await direct.text()).not.toContain('Blue Stoneware Mug');
  });
});
