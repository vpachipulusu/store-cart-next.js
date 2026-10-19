/** KAN-74: the import dialog checks the file, sends it with the rendered store id and lists row problems. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ importProductsAction: vi.fn() }));

vi.mock('@/app/actions/product-import-actions', () => ({
  importProductsAction: mocks.importProductsAction,
}));

import { ProductImportDialog } from '@/components/dashboard/products/product-import-dialog';
import { SAMPLE_CSV, SAMPLE_FILE_NAME, WRONG_TYPE_MESSAGE } from '@/lib/products/csv-import';

const csv = () =>
  new File(['title,sku,price_minor\nA,A-1,1\n'], 'products.csv', { type: 'text/csv' });

async function openDialog() {
  const user = userEvent.setup();
  render(<ProductImportDialog storeId="store1" storeName="Corner Shop" />);
  await user.click(screen.getByRole('button', { name: 'Import CSV' }));
  return user;
}

async function importFile(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByLabelText('CSV file'), csv());
  await user.click(screen.getByRole('button', { name: 'Import' }));
}

describe('ProductImportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('explains the format for the named store', async () => {
    await openDialog();

    const dialog = screen.getByRole('dialog', { name: 'Import products' });
    expect(within(dialog).getByText(/Add products to Corner Shop/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Columns: title, slug/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('imports the chosen file for the rendered store and reports the count', async () => {
    mocks.importProductsAction.mockResolvedValue({
      success: true,
      data: { imported: 2, errors: [], truncated: false },
    });
    const user = await openDialog();

    await importFile(user);

    expect(await screen.findByText('Imported 2 products.')).toBeInTheDocument();
    const [storeId, formData] = mocks.importProductsAction.mock.calls[0];
    expect(storeId).toBe('store1');
    expect((formData as FormData).get('file')).toBeInstanceOf(File);
  });

  it('lists every problem by row and column', async () => {
    mocks.importProductsAction.mockResolvedValue({
      success: true,
      data: {
        imported: 0,
        errors: [
          { row: 3, column: 'sku', message: 'SKU is already in use' },
          { row: null, column: null, message: 'The file has no product rows' },
        ],
        truncated: true,
      },
    });
    const user = await openDialog();

    await importFile(user);

    expect(await screen.findByText(/Nothing was imported. Fix 2 problems/)).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Problems in the file' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Row 3')).toBeInTheDocument();
    expect(within(rows[0]).getByText('sku')).toBeInTheDocument();
    expect(within(rows[0]).getByText('SKU is already in use')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Whole file')).toBeInTheDocument();
    expect(screen.getByText(/Only the first problems are listed/)).toBeInTheDocument();
  });

  it('refuses a non-csv file without calling the action', async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<ProductImportDialog storeId="store1" storeName="Shop" />);
    await user.click(screen.getByRole('button', { name: 'Import CSV' }));

    await user.upload(
      screen.getByLabelText('CSV file'),
      new File(['x'], 'products.xlsx', { type: 'application/octet-stream' })
    );

    expect(screen.getByRole('alert')).toHaveTextContent(WRONG_TYPE_MESSAGE);
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
    expect(mocks.importProductsAction).not.toHaveBeenCalled();
  });

  it('shows the action error', async () => {
    mocks.importProductsAction.mockResolvedValue({
      success: false,
      error: 'The selected store changed. Reload the page and try again.',
    });
    const user = await openDialog();

    await importFile(user);

    expect(await screen.findByText(/selected store changed/)).toBeInTheDocument();
  });

  it('shows a fixed message when the action throws', async () => {
    mocks.importProductsAction.mockRejectedValue(new Error('network'));
    const user = await openDialog();

    await importFile(user);

    expect(await screen.findByText('The request failed. Please try again.')).toBeInTheDocument();
  });

  it('clears the result when closed and reopened', async () => {
    mocks.importProductsAction.mockResolvedValue({
      success: true,
      data: { imported: 1, errors: [], truncated: false },
    });
    const user = await openDialog();
    await importFile(user);
    await screen.findByText('Imported 1 product.');

    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Import CSV' }));

    expect(screen.queryByText('Imported 1 product.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('downloads the sample CSV', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:sample');
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const user = await openDialog();

    await user.click(screen.getByRole('button', { name: 'Download sample CSV' }));

    const anchor = click.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toBe(SAMPLE_FILE_NAME);
    const blob = createObjectURL.mock.calls[0][0];
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(text).toBe(SAMPLE_CSV);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:sample');
    click.mockRestore();
  });
});
