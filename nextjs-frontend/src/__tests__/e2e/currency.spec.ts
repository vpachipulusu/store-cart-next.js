import { test, expect } from '@playwright/test';
import { waitForPageReady } from './helpers/e2e-utils';

/**
 * Currency Display E2E Tests
 *
 * Verifies that the pricing page displays currency symbols
 * consistently across all pricing tiers.
 */

test.describe('Currency Display on Pricing Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/pricing');
    await waitForPageReady(page);
  });

  test('should display a currency symbol next to each price', async ({ page }) => {
    // Each pricing card should show a currency symbol followed by a number
    const priceElements = page.locator('.text-4xl.font-bold');
    const count = await priceElements.count();

    expect(count).toBeGreaterThanOrEqual(3);

    for (let i = 0; i < count; i++) {
      const text = await priceElements.nth(i).textContent();
      // Should match a currency symbol followed by a number (e.g. $0, €29, £99)
      expect(text).toMatch(/^.+\d+$/);
    }
  });

  test('should display consistent currency symbol across all tiers', async ({ page }) => {
    const priceElements = page.locator('.text-4xl.font-bold');
    const count = await priceElements.count();

    expect(count).toBeGreaterThanOrEqual(3);

    // Extract the currency symbol from each price (everything before the first digit)
    const symbols: string[] = [];
    for (let i = 0; i < count; i++) {
      const text = (await priceElements.nth(i).textContent()) || '';
      const symbol = text.replace(/\d+.*$/, '');
      symbols.push(symbol);
    }

    // All symbols should be the same
    const uniqueSymbols = [...new Set(symbols)];
    expect(uniqueSymbols).toHaveLength(1);
  });

  test('should display free tier with currency symbol and zero', async ({ page }) => {
    const freeCard = page.locator('[class*="card"]').filter({ hasText: /^Free$/ });
    await expect(freeCard).toBeVisible();

    // Free tier should show the currency symbol followed by 0
    const priceElement = freeCard.locator('.text-4xl.font-bold');
    const text = await priceElement.textContent();
    expect(text).toMatch(/^.+0$/);
  });

  test('should not show /month for the free tier', async ({ page }) => {
    const freeCard = page.locator('[class*="card"]').filter({ hasText: /^Free$/ });
    await expect(freeCard).toBeVisible();

    // Free tier should not show "/month" since price is 0
    await expect(freeCard.getByText('/month')).not.toBeVisible();
  });

  test('should show /month for paid tiers', async ({ page }) => {
    const proCard = page.locator('[class*="card"]').filter({ hasText: /^Pro$/ });
    await expect(proCard.getByText('/month').first()).toBeVisible();
  });
});
