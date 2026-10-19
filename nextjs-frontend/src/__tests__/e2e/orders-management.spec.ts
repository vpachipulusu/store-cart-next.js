import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';
import { BACKEND_DIR, seedActiveStore } from './helpers/products-e2e';
import { seedOrders } from './helpers/orders-e2e';

/**
 * KAN-79: merchant order list, detail and manual fulfilment. Needs the FastAPI backend (BACKEND_API_URL,
 * BACKEND_INTERNAL_KEY) and E2E_BACKEND_DIR. See helpers/orders-e2e.ts and docs/developer/local-e2e.md.
 */

test.describe('Merchant order management', () => {
  test.skip(!BACKEND_DIR, 'Needs E2E_BACKEND_DIR and a running backend');
  test.setTimeout(240_000);

  test('lists, filters, shows and fulfils orders', async ({ page, throwawayAccount }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    const storeId = await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));
    seedOrders(storeId);

    // The store starts with a paid and a pending order, newest first.
    await page.goto('/dashboard/orders');
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Orders' })).toBeVisible();
    await expect(page.getByTestId('order-row')).toHaveCount(2);
    await expect(page.getByTestId('order-row').first()).toContainText('Pending');
    await expect(page.getByTestId('order-row').last()).toContainText('Paid');

    // The server applies the status filter.
    await page.getByLabel('Status').selectOption('paid');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('order-row')).toHaveCount(1);
    await page.getByLabel('Status').selectOption('cancelled');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByTestId('no-orders')).toContainText('No orders match this filter.');
    await page.getByRole('link', { name: 'Clear filter' }).click();
    await expect(page.getByTestId('order-row')).toHaveCount(2);

    // A pending order cannot be fulfilled yet.
    await page.getByTestId('order-row').first().getByRole('link').click();
    await waitForPageReady(page);
    await expect(page.getByTestId('order-item')).toContainText('E2E Order Tee');
    await expect(page.getByText('This order can be fulfilled once it is paid.')).toBeVisible();
    await expect(page.getByLabel('Tracking number')).toHaveCount(0);

    // The paid order: totals and snapshot, then validation, then fulfilment with a tracking number.
    await page.goto('/dashboard/orders?status=paid');
    await waitForPageReady(page);
    await page.getByTestId('order-row').first().getByRole('link').click();
    await waitForPageReady(page);
    await expect(page.getByTestId('order-item')).toContainText('E2E-ORDER-1');
    await expect(page.getByText('£47.98')).toBeVisible();

    await page.getByRole('button', { name: 'Mark as fulfilled' }).click();
    await expect(page.getByRole('form', { name: 'Fulfil order' }).getByRole('alert')).toContainText(
      'Tracking number is required'
    );

    await page.getByLabel('Tracking number').fill('RM123456789GB');
    await page.getByLabel('Carrier (optional)').fill('Royal Mail');
    await page.getByRole('button', { name: 'Mark as fulfilled' }).click();
    await expect(page.getByTestId('tracking-number')).toHaveText('RM123456789GB');
    await expect(page.getByText('Royal Mail')).toBeVisible();
    await expect(page.getByLabel('Tracking number')).toHaveCount(0);

    // It persists, and the list shows the new status and tracking number.
    await page.goto('/dashboard/orders?status=fulfilled');
    await waitForPageReady(page);
    await expect(page.getByTestId('order-row')).toHaveCount(1);
    await expect(page.getByTestId('order-row')).toContainText('RM123456789GB');
  });

  test('an unknown order id is a not-found page', async ({ page, throwawayAccount }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));

    const response = await page.goto('/dashboard/orders/does-not-exist');

    expect(response?.status()).toBe(404);
  });
});
