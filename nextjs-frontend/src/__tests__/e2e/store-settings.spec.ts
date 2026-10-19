import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';
import { BACKEND_DIR, seedActiveStore } from './helpers/products-e2e';

/**
 * KAN-82, KAN-83: the merchant shipping and tax settings page. Needs the FastAPI backend (BACKEND_API_URL,
 * BACKEND_INTERNAL_KEY) and E2E_BACKEND_DIR to seed an ACTIVE store. See helpers/products-e2e.ts and
 * docs/developer/local-e2e.md.
 */

test.describe('Store shipping and tax settings', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Needs BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR (see docs/developer/local-e2e.md)'
  );

  test('a merchant sets shipping and tax, sees validation, and the values persist', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));

    // The nav links to the page.
    await page.goto('/dashboard');
    await waitForPageReady(page);
    await page
      .getByRole('navigation')
      .getByRole('link', { name: 'Shipping and tax' })
      .first()
      .click();
    await expect(page).toHaveURL(/\/dashboard\/settings\/store$/);
    await waitForPageReady(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Shipping and tax' })).toBeVisible();

    // A new store has no shipping charge and no tax.
    const flatRate = page.getByLabel(/^Flat shipping rate/);
    const threshold = page.getByLabel(/^Free shipping over/);
    const taxRate = page.getByLabel(/^Tax rate/);
    const includeTax = page.getByRole('switch', { name: 'Prices include tax' });
    await expect(flatRate).toHaveValue('0.00');
    await expect(threshold).toHaveValue('');
    await expect(taxRate).toHaveValue('0');
    await expect(includeTax).not.toBeChecked();

    // Validation: bad values are refused before the server, with one message per field.
    await flatRate.fill('abc');
    await taxRate.fill('150');
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(page.getByText('Enter an amount like 4.99')).toBeVisible();
    await expect(page.getByText('Enter a percentage from 0 to 100')).toBeVisible();

    // A valid save reports success.
    await flatRate.fill('4.99');
    await threshold.fill('50');
    await taxRate.fill('7.5');
    await includeTax.click();
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Settings saved.' })).toBeVisible();

    // The values survive a reload, shown back in major units and percent.
    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByLabel(/^Flat shipping rate/)).toHaveValue('4.99');
    await expect(page.getByLabel(/^Free shipping over/)).toHaveValue('50.00');
    await expect(page.getByLabel(/^Tax rate/)).toHaveValue('7.5');
    await expect(page.getByRole('switch', { name: 'Prices include tax' })).toBeChecked();

    // Clearing the threshold removes free shipping.
    await page.getByLabel(/^Free shipping over/).fill('');
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Settings saved.' })).toBeVisible();
    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByLabel(/^Free shipping over/)).toHaveValue('');
  });
});
