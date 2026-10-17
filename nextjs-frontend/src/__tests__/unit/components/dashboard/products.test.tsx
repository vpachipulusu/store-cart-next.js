/** KAN-73: the product list table, category field, create form and editor behave as a merchant expects. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  createProductAction: vi.fn(),
  updateProductAction: vi.fn(),
  deleteProductAction: vi.fn(),
  addVariantAction: vi.fn(),
  updateVariantAction: vi.fn(),
  deleteVariantAction: vi.fn(),
  deleteImageAction: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/app/actions/product-actions', () => ({
  createProductAction: mocks.createProductAction,
  updateProductAction: mocks.updateProductAction,
  deleteProductAction: mocks.deleteProductAction,
  addVariantAction: mocks.addVariantAction,
  updateVariantAction: mocks.updateVariantAction,
  deleteVariantAction: mocks.deleteVariantAction,
  deleteImageAction: mocks.deleteImageAction,
}));

import { CategoriesField } from '@/components/dashboard/products/categories-field';
import { ProductCreateForm } from '@/components/dashboard/products/product-create-form';
import { ProductEditor } from '@/components/dashboard/products/product-editor';
import { ProductTable, type ProductRow } from '@/components/dashboard/products/product-table';
import type { ProductData } from '@/lib/api/products';

const rows: ProductRow[] = [
  {
    id: 'p1',
    title: 'Blue Tee',
    slug: 'blue-tee',
    status: 'active',
    variantCount: 3,
    price: '$10.00 – $12.00',
    updated: '1 Jan 2026',
  },
  {
    id: 'p2',
    title: 'Red Mug',
    slug: 'red-mug',
    status: 'draft',
    variantCount: 1,
    price: null,
    updated: '2 Jan 2026',
  },
];

function makeProduct(overrides: Partial<ProductData> = {}): ProductData {
  return {
    id: 'p1',
    title: 'Blue Tee',
    slug: 'blue-tee',
    description: 'Soft',
    status: 'draft',
    currency: 'USD',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    options: [],
    variants: [
      {
        id: 'v1',
        sku: 'TEE-1',
        price_minor: 1250,
        compare_at_price_minor: null,
        weight_grams: null,
        stock: 4,
        position: 0,
        option_values: [],
      },
    ],
    category_ids: ['cat1'],
    images: [{ id: 'i1', storage_key: 'stores/s1/img.png', alt_text: 'Front', position: 1 }],
    ...overrides,
  };
}

const sizeOption = {
  id: 'o1',
  name: 'Size',
  position: 0,
  values: [
    { id: 'ov1', value: 'S', position: 0 },
    { id: 'ov2', value: 'M', position: 1 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ProductTable', () => {
  it('links each product to its editor and shows status, count and price', () => {
    render(<ProductTable rows={rows} />);
    expect(screen.getByRole('link', { name: 'Blue Tee' })).toHaveAttribute(
      'href',
      '/dashboard/products/p1'
    );
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Draft')).toBeInTheDocument();
    expect(screen.getByText('$10.00 – $12.00')).toBeInTheDocument();
  });

  it('narrows only the loaded rows and says store-wide search is unavailable', async () => {
    const user = userEvent.setup();
    render(<ProductTable rows={rows} />);
    expect(screen.getByText(/store-wide search is not available yet/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Filter this page by title'), 'mug');

    expect(screen.queryByRole('link', { name: 'Blue Tee' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Red Mug' })).toBeInTheDocument();
  });

  it('says so when nothing on the page matches', async () => {
    const user = userEvent.setup();
    render(<ProductTable rows={rows} />);
    await user.type(screen.getByLabelText('Filter this page by title'), 'zzz');
    expect(screen.getByRole('status')).toHaveTextContent('No products on this page match');
  });
});

describe('CategoriesField', () => {
  it('adds a valid id, rejects duplicates and bad ids, and removes an id', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<CategoriesField value={['cat1']} onChange={onChange} />);

    await user.type(screen.getByLabelText('Category id'), 'cat2');
    await user.click(screen.getByRole('button', { name: 'Add category' }));
    expect(onChange).toHaveBeenCalledWith(['cat1', 'cat2']);

    await user.type(screen.getByLabelText('Category id'), 'cat1');
    await user.click(screen.getByRole('button', { name: 'Add category' }));
    expect(screen.getByRole('alert')).toHaveTextContent('already added');

    await user.clear(screen.getByLabelText('Category id'));
    await user.type(screen.getByLabelText('Category id'), 'bad id!');
    await user.click(screen.getByRole('button', { name: 'Add category' }));
    expect(screen.getByRole('alert')).toHaveTextContent('valid category id');

    await user.click(screen.getByRole('button', { name: 'Remove category cat1' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('explains that categories can only be handled by id', () => {
    render(<CategoriesField value={[]} onChange={vi.fn()} />);
    expect(screen.getByText(/categories show by id/i)).toBeInTheDocument();
  });
});

describe('ProductCreateForm', () => {
  it('shows field errors and does not call the server for an empty form', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" />);

    await user.click(screen.getByRole('button', { name: 'Create product' }));

    expect(await screen.findByText('Title is required')).toBeInTheDocument();
    expect(screen.getByText('Enter a price like 12.50')).toBeInTheDocument();
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('creates a product with money in minor units and opens its editor', async () => {
    const user = userEvent.setup();
    mocks.createProductAction.mockResolvedValue({ success: true, data: makeProduct() });
    render(<ProductCreateForm currency="USD" />);

    await user.type(screen.getByLabelText('Title'), 'Blue Tee');
    await user.type(screen.getByLabelText('SKU'), 'TEE-1');
    await user.type(screen.getByLabelText('Price (USD)'), '12.50');
    await user.clear(screen.getByLabelText('Stock'));
    await user.type(screen.getByLabelText('Stock'), '4');
    await user.click(screen.getByRole('button', { name: 'Create product' }));

    expect(mocks.createProductAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Blue Tee',
        status: 'draft',
        options: [],
        variants: [
          expect.objectContaining({ sku: 'TEE-1', priceMinor: 1250, stock: 4, weightGrams: null }),
        ],
      })
    );
    expect(mocks.push).toHaveBeenCalledWith('/dashboard/products/p1');
  });

  it('builds one variant row per option combination', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" />);
    expect(screen.getAllByTestId('variant-row')).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Add option' }));
    await user.type(screen.getByLabelText('Option 1 name'), 'Size');
    await user.type(screen.getByLabelText('Option 1 values'), 'S, M, L');

    expect(screen.getAllByTestId('variant-row')).toHaveLength(3);
  });

  it('shows the curated server error and lets the merchant retry', async () => {
    const user = userEvent.setup();
    mocks.createProductAction.mockResolvedValue({
      success: false,
      error: 'SKU already exists in this store',
    });
    render(<ProductCreateForm currency="USD" />);

    await user.type(screen.getByLabelText('Title'), 'Blue Tee');
    await user.type(screen.getByLabelText('SKU'), 'TEE-1');
    await user.type(screen.getByLabelText('Price (USD)'), '10');
    await user.click(screen.getByRole('button', { name: 'Create product' }));

    expect(await screen.findByText('SKU already exists in this store')).toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Create product' })).toBeEnabled();
  });

  it('rejects decimals for a zero-decimal currency', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="JPY" />);
    await user.type(screen.getByLabelText('Title'), 'Tee');
    await user.type(screen.getByLabelText('SKU'), 'T');
    await user.type(screen.getByLabelText('Price (JPY)'), '10.5');
    await user.click(screen.getByRole('button', { name: 'Create product' }));
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });
});

describe('ProductEditor', () => {
  it('saves details through the update action', async () => {
    const user = userEvent.setup();
    const saved = makeProduct({ title: 'Green Tee', updated_at: '2026-02-01T00:00:00Z' });
    mocks.updateProductAction.mockResolvedValue({ success: true, data: saved });
    render(<ProductEditor initial={makeProduct()} />);

    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Green Tee');
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    expect(mocks.updateProductAction).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ title: 'Green Tee', categoryIds: ['cat1'], status: 'draft' })
    );
    expect(await screen.findByRole('heading', { level: 1, name: 'Green Tee' })).toBeInTheDocument();
  });

  it('shows a server error from saving details', async () => {
    const user = userEvent.setup();
    mocks.updateProductAction.mockResolvedValue({ success: false, error: 'Unknown category' });
    render(<ProductEditor initial={makeProduct()} />);
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByText('Unknown category')).toBeInTheDocument();
  });

  it('shows prices in major units and saves an edited variant in minor units', async () => {
    const user = userEvent.setup();
    mocks.updateVariantAction.mockResolvedValue({ success: true, data: makeProduct() });
    render(<ProductEditor initial={makeProduct()} />);

    const price = screen.getByLabelText('Price (USD)');
    expect(price).toHaveValue('12.50');
    await user.clear(price);
    await user.type(price, '19.99');
    await user.click(screen.getByRole('button', { name: 'Save variant' }));

    expect(mocks.updateVariantAction).toHaveBeenCalledWith(
      'p1',
      'v1',
      expect.objectContaining({ sku: 'TEE-1', priceMinor: 1999, stock: 4 })
    );
  });

  it('blocks an invalid variant edit before the server', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} />);
    const price = screen.getByLabelText('Price (USD)');
    await user.clear(price);
    await user.type(price, 'abc');
    await user.click(screen.getByRole('button', { name: 'Save variant' }));
    expect(screen.getByText('Enter a price like 12.50')).toBeInTheDocument();
    expect(mocks.updateVariantAction).not.toHaveBeenCalled();
  });

  it('needs a second click to delete a variant and relays the last-variant error', async () => {
    const user = userEvent.setup();
    mocks.deleteVariantAction.mockResolvedValue({
      success: false,
      error: 'A product needs at least one variant',
    });
    render(<ProductEditor initial={makeProduct()} />);

    await user.click(screen.getByRole('button', { name: 'Delete variant' }));
    expect(mocks.deleteVariantAction).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm delete variant' }));

    expect(mocks.deleteVariantAction).toHaveBeenCalledWith('p1', 'v1');
    expect(await screen.findByText('A product needs at least one variant')).toBeInTheDocument();
  });

  it('adds a variant to a product with options, using the chosen option value', async () => {
    const user = userEvent.setup();
    const withOptions = makeProduct({
      options: [sizeOption],
      variants: [
        {
          ...makeProduct().variants[0],
          option_values: [{ option_id: 'o1', option_value_id: 'ov1' }],
        },
      ],
    });
    mocks.addVariantAction.mockResolvedValue({ success: true, data: withOptions });
    render(<ProductEditor initial={withOptions} />);

    const form = screen.getByRole('form', { name: 'Add variant' });
    await user.selectOptions(within(form).getByLabelText('Size'), 'M');
    await user.type(within(form).getByLabelText('SKU'), 'TEE-M');
    await user.type(within(form).getByLabelText('Price (USD)'), '13');
    await user.click(within(form).getByRole('button', { name: 'Add variant' }));

    expect(mocks.addVariantAction).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ sku: 'TEE-M', priceMinor: 1300, options: { Size: 'M' } })
    );
  });

  it('explains why a product without options cannot get more variants', () => {
    render(<ProductEditor initial={makeProduct()} />);
    expect(screen.getByTestId('no-add-variant')).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Add variant' })).not.toBeInTheDocument();
  });

  it('asks for a choice for every option before adding a variant', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct({ options: [sizeOption] })} />);
    const form = screen.getByRole('form', { name: 'Add variant' });
    await user.click(within(form).getByRole('button', { name: 'Add variant' }));
    expect(within(form).getByText('Choose a value for Size.')).toBeInTheDocument();
    expect(mocks.addVariantAction).not.toHaveBeenCalled();
  });

  it('lists images with a remove action and no upload control', async () => {
    const user = userEvent.setup();
    mocks.deleteImageAction.mockResolvedValue({
      success: true,
      data: makeProduct({ images: [] }),
    });
    render(<ProductEditor initial={makeProduct()} />);

    expect(screen.getByText('stores/s1/img.png')).toBeInTheDocument();
    expect(screen.getByText(/uploading new images .* is not available yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/upload/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Remove image 1' }));
    await user.click(screen.getByRole('button', { name: 'Remove image' }));

    expect(mocks.deleteImageAction).toHaveBeenCalledWith('p1', 'i1');
    expect(await screen.findByTestId('no-images')).toBeInTheDocument();
  });

  it('deletes the product after confirmation and returns to the list', async () => {
    const user = userEvent.setup();
    mocks.deleteProductAction.mockResolvedValue({ success: true, data: { deleted: true } });
    render(<ProductEditor initial={makeProduct()} />);

    await user.click(screen.getByRole('button', { name: 'Delete product' }));
    expect(mocks.deleteProductAction).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm delete product' }));

    expect(mocks.deleteProductAction).toHaveBeenCalledWith('p1');
    expect(mocks.push).toHaveBeenCalledWith('/dashboard/products');
  });

  it('keeps the product and shows the error when deletion fails', async () => {
    const user = userEvent.setup();
    mocks.deleteProductAction.mockResolvedValue({ success: false, error: 'Product not found' });
    render(<ProductEditor initial={makeProduct()} />);
    await user.click(screen.getByRole('button', { name: 'Delete product' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete product' }));
    expect(await screen.findByText('Product not found')).toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });
});

describe('ProductEditor save feedback', () => {
  it('keeps showing "Variant saved." and the server value when the saved values change', async () => {
    const user = userEvent.setup();
    const base = makeProduct();
    mocks.updateVariantAction.mockResolvedValue({
      success: true,
      data: makeProduct({
        updated_at: '2026-03-01T00:00:00Z',
        variants: [{ ...base.variants[0], price_minor: 2000 }],
      }),
    });
    render(<ProductEditor initial={base} />);

    const price = screen.getByLabelText('Price (USD)');
    await user.clear(price);
    await user.type(price, '19.99');
    await user.click(screen.getByRole('button', { name: 'Save variant' }));

    expect(await screen.findByText('Variant saved.')).toBeInTheDocument();
    expect(screen.getByLabelText('Price (USD)')).toHaveValue('20.00');
  });

  it('keeps an unsaved title when a variant is saved with a newer product timestamp', async () => {
    const user = userEvent.setup();
    mocks.updateVariantAction.mockResolvedValue({
      success: true,
      data: makeProduct({ updated_at: '2026-03-01T00:00:00Z' }),
    });
    render(<ProductEditor initial={makeProduct()} />);

    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Unsaved name');
    await user.click(screen.getByRole('button', { name: 'Save variant' }));

    expect(await screen.findByText('Variant saved.')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('Unsaved name');
  });

  it('shows "Product saved." after details change the product timestamp', async () => {
    const user = userEvent.setup();
    mocks.updateProductAction.mockResolvedValue({
      success: true,
      data: makeProduct({ status: 'active', updated_at: '2026-03-01T00:00:00Z' }),
    });
    render(<ProductEditor initial={makeProduct()} />);
    await user.selectOptions(screen.getByLabelText('Status'), 'active');
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByText('Product saved.')).toBeInTheDocument();
  });

  it('does not submit the product form when Enter is pressed in the category box', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} />);
    await user.type(screen.getByLabelText('Category id'), 'cat2{Enter}');
    expect(mocks.updateProductAction).not.toHaveBeenCalled();
    expect(screen.getByText('cat2')).toBeInTheDocument();
  });
});

describe('ProductCreateForm options', () => {
  it('refuses a half-filled option row instead of silently dropping it', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" />);
    await user.type(screen.getByLabelText('Title'), 'Tee');
    await user.type(screen.getByLabelText('SKU'), 'T');
    await user.type(screen.getByLabelText('Price (USD)'), '5');
    await user.click(screen.getByRole('button', { name: 'Add option' }));
    await user.type(screen.getByLabelText('Option 1 name'), 'Size');
    await user.click(screen.getByRole('button', { name: 'Create product' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Each option needs a name');
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('keeps typed row data when another option value is added', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" />);
    await user.click(screen.getByRole('button', { name: 'Add option' }));
    await user.type(screen.getByLabelText('Option 1 name'), 'Size');
    await user.type(screen.getByLabelText('Option 1 values'), 'S');
    await user.type(screen.getByLabelText('SKU'), 'E-S');
    await user.type(screen.getByLabelText('Option 1 values'), ', M');
    expect(screen.getAllByTestId('variant-row')).toHaveLength(2);
    expect(within(screen.getAllByTestId('variant-row')[0]).getByLabelText('SKU')).toHaveValue(
      'E-S'
    );
  });
});
