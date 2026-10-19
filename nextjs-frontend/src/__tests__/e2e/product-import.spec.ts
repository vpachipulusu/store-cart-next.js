import { test, expect } from './helpers/fixtures';
import { loginAsThrowawayAccount, waitForPageReady } from './helpers/e2e-utils';
import { BACKEND_DIR, seedActiveStore } from './helpers/products-e2e';

/**
 * KAN-74: product CSV import from the products page. A file with bad rows imports nothing and lists the problems by
 * row and column; the fixed file imports every row. Needs the FastAPI backend (BACKEND_API_URL, BACKEND_INTERNAL_KEY)
 * and E2E_BACKEND_DIR, like product-management.spec.ts (docs/developer/local-e2e.md).
 */

const HEADER =
  'title,slug,description,status,sku,price_minor,compare_at_price_minor,weight_grams,stock';

function csv(...rows: string[]): { name: string; mimeType: string; buffer: Buffer } {
  return {
    name: 'products.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from([HEADER, ...rows].join('\n') + '\n'),
  };
}

test.describe('Product CSV import', () => {
  test.skip(
    !process.env.BACKEND_INTERNAL_KEY || !BACKEND_DIR,
    'Skipped: BACKEND_INTERNAL_KEY and E2E_BACKEND_DIR not set (needs FastAPI and uv)'
  );
  test.setTimeout(300_000);

  test('reports row errors, imports nothing, then imports the fixed file', async ({
    page,
    throwawayAccount,
  }) => {
    await loginAsThrowawayAccount(page, throwawayAccount);
    await seedActiveStore(page, throwawayAccount.email.split('@')[0].slice(-12));
    await page.goto('/dashboard/products');
    await waitForPageReady(page);
    await expect(page.getByTestId('no-products')).toBeVisible();

    await page.getByRole('button', { name: 'Import CSV' }).click();
    const dialog = page.getByRole('dialog', { name: 'Import products' });
    const download = page.waitForEvent('download');
    await dialog.getByRole('button', { name: 'Download sample CSV' }).click();
    expect((await download).suggestedFilename()).toBe('products-import-sample.csv');

    // A non-CSV file is refused in the browser.
    const fileInput = dialog.getByLabel('CSV file');
    await fileInput.setInputFiles({
      name: 'products.xlsx',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('x'),
    });
    await expect(dialog.getByText('Choose a .csv file.')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Import' })).toBeDisabled();

    // One good row, one bad price and one formula title: nothing is imported, both problems are listed.
    await fileInput.setInputFiles(
      csv(
        'Blue Lamp,,Brass,active,E2E-LAMP-1,4500,,900,3',
        'Red Lamp,,,draft,E2E-LAMP-2,12.50,,,',
        '=1+1,,,draft,E2E-LAMP-3,100,,,'
      )
    );
    await dialog.getByRole('button', { name: 'Import' }).click();
    const problems = dialog.getByRole('table', { name: 'Problems in the file' });
    await expect(problems).toBeVisible();
    await expect(dialog.getByText(/Nothing was imported. Fix 2 problems/)).toBeVisible();
    const rows = problems.getByRole('row');
    await expect(rows.nth(1)).toContainText('Row 3');
    await expect(rows.nth(1)).toContainText('price_minor');
    await expect(rows.nth(2)).toContainText('Row 4');
    await expect(rows.nth(2)).toContainText('title');

    // The fixed file imports both rows.
    await fileInput.setInputFiles(
      csv('Blue Lamp,,Brass,active,E2E-LAMP-1,4500,,900,3', 'Red Lamp,,,draft,E2E-LAMP-2,1250,,,')
    );
    await dialog.getByRole('button', { name: 'Import' }).click();
    await expect(dialog.getByTestId('import-success')).toHaveText('Imported 2 products.');

    await page.keyboard.press('Escape');
    await page.reload();
    await waitForPageReady(page);
    await expect(page.getByTestId('product-row')).toHaveCount(2);
    await expect(page.getByRole('link', { name: 'Blue Lamp' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Red Lamp' })).toBeVisible();

    // Importing a SKU the store already has is refused per row and adds nothing.
    await page.getByRole('button', { name: 'Import CSV' }).click();
    await dialog.getByLabel('CSV file').setInputFiles(csv('Green Lamp,,,draft,e2e-lamp-1,100,,,'));
    await dialog.getByRole('button', { name: 'Import' }).click();
    await expect(dialog.getByRole('table', { name: 'Problems in the file' })).toContainText(
      'SKU is already in use'
    );
  });
});
