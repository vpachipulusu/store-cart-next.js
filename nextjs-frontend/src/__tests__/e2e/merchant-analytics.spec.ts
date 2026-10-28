import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';
import { BACKEND_DIR, seedActiveStore } from './helpers/products-e2e';
import { seedOrders } from './helpers/orders-e2e';

/**
 * KAN-96: the merchant analytics page. Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY) and
 * E2E_BACKEND_DIR, like orders-management.spec.ts. seedOrders adds a PAID order (2 x £19.99 plus 20% tax, £47.98)
 * and a PENDING one, both placed today, so the default range (the last 30 UTC days) holds exactly one sale.
 */

test.describe('Merchant analytics', () => {
  test.skip(!BACKEND_DIR, 'Needs E2E_BACKEND_DIR and a running backend');
  test.setTimeout(240_000);

  test('shows sales, orders and top products and changes the range', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    const storeId = await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));
    seedOrders(storeId);

    await page.goto('/dashboard/analytics');
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Analytics' })).toBeVisible();

    // Only the paid order counts; the pending one is not a sale.
    const pounds = page.getByTestId('analytics-GBP');
    await expect(pounds.getByRole('group', { name: 'Net sales' })).toContainText('£47.98');
    await expect(pounds.getByRole('group', { name: 'Refunds' })).toContainText('£0.00');
    await expect(pounds.getByRole('group', { name: 'Orders' })).toContainText('1');
    await expect(pounds.getByTestId('sales-row')).toHaveCount(30);
    const topRevenue = pounds.getByRole('table', { name: 'Top products by revenue' });
    await expect(topRevenue.getByTestId('top-product-row')).toHaveCount(1);
    await expect(topRevenue.getByTestId('top-product-row')).toContainText('E2E Order Tee');
    await expect(topRevenue.getByTestId('top-product-row')).toContainText('£39.98');

    // Monthly buckets: one or two months, depending on today's date.
    await page.getByLabel('Group by').selectOption('month');
    await page.getByRole('button', { name: 'Apply' }).click();
    await waitForPageReady(page);
    await expect(page).toHaveURL(/bucket=month/);
    await expect(page.getByRole('table', { name: 'Monthly sales in GBP' })).toBeVisible();

    // A range without sales is the empty state.
    await page.goto('/dashboard/analytics?from=2020-01-01&to=2020-01-31');
    await waitForPageReady(page);
    await expect(page.getByTestId('no-sales')).toContainText('No sales in this period.');

    // The backend's range message is shown for a range it refuses.
    await page.goto('/dashboard/analytics?from=2020-02-01&to=2020-01-01');
    await waitForPageReady(page);
    await expect(page.getByRole('alert')).toContainText(
      'The start date must be on or before the end date'
    );
  });

  test('the nav links to analytics', async ({ page, throwawayAccount }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));

    await page.goto('/dashboard/analytics');
    await waitForPageReady(page);

    await expect(page.getByRole('link', { name: 'Analytics' }).first()).toHaveAttribute(
      'href',
      '/dashboard/analytics'
    );
    await expect(page.getByTestId('no-sales')).toBeVisible();
  });
});
