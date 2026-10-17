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

  it('renders no page-only filter: search runs on the server', () => {
    render(<ProductTable rows={rows} />);
    expect(screen.queryByLabelText('Filter this page by title')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('product-row')).toHaveLength(2);
  });
});

describe('CategoriesField', () => {
  it('adds a valid id, rejects duplicates and bad ids, and removes an id', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<CategoriesField value={['cat1']} onChange={onChange} categories={null} />);

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
    render(<CategoriesField value={[]} onChange={vi.fn()} categories={null} />);
    expect(screen.getByText(/categories show by id/i)).toBeInTheDocument();
  });
});

describe('ProductCreateForm', () => {
  it('shows field errors and does not call the server for an empty form', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);

    await user.click(screen.getByRole('button', { name: 'Create product' }));

    expect(await screen.findByText('Title is required')).toBeInTheDocument();
    expect(screen.getByText('Enter a price like 12.50')).toBeInTheDocument();
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('creates a product with money in minor units and opens its editor', async () => {
    const user = userEvent.setup();
    mocks.createProductAction.mockResolvedValue({ success: true, data: makeProduct() });
    render(<ProductCreateForm currency="USD" categories={null} />);

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
    render(<ProductCreateForm currency="USD" categories={null} />);
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
    render(<ProductCreateForm currency="USD" categories={null} />);

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
    render(<ProductCreateForm currency="JPY" categories={null} />);
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
    render(<ProductEditor initial={makeProduct()} categories={null} />);

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
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByText('Unknown category')).toBeInTheDocument();
  });

  it('shows prices in major units and saves an edited variant in minor units', async () => {
    const user = userEvent.setup();
    mocks.updateVariantAction.mockResolvedValue({ success: true, data: makeProduct() });
    render(<ProductEditor initial={makeProduct()} categories={null} />);

    const price = screen.getByLabelText('Price (USD)');
    expect(price).toHaveValue('12.50');
    await user.clear(price);
    await user.type(price, '19.99');
    await user.click(screen.getByRole('button', { name: /^Save variant/ }));

    expect(mocks.updateVariantAction).toHaveBeenCalledWith(
      'p1',
      'v1',
      expect.objectContaining({ sku: 'TEE-1', priceMinor: 1999, stock: 4 })
    );
  });

  it('blocks an invalid variant edit before the server', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    const price = screen.getByLabelText('Price (USD)');
    await user.clear(price);
    await user.type(price, 'abc');
    await user.click(screen.getByRole('button', { name: /^Save variant/ }));
    expect(screen.getByText('Enter a price like 12.50')).toBeInTheDocument();
    expect(mocks.updateVariantAction).not.toHaveBeenCalled();
  });

  it('needs a second click to delete a variant and relays the last-variant error', async () => {
    const user = userEvent.setup();
    mocks.deleteVariantAction.mockResolvedValue({
      success: false,
      error: 'A product needs at least one variant',
    });
    render(<ProductEditor initial={makeProduct()} categories={null} />);

    await user.click(screen.getByRole('button', { name: /^Delete variant/ }));
    expect(mocks.deleteVariantAction).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /^Confirm delete variant/ }));

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
    render(<ProductEditor initial={withOptions} categories={null} />);

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
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    expect(screen.getByTestId('no-add-variant')).toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Add variant' })).not.toBeInTheDocument();
  });

  it('asks for a choice for every option before adding a variant', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct({ options: [sizeOption] })} categories={null} />);
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
    render(<ProductEditor initial={makeProduct()} categories={null} />);

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
    render(<ProductEditor initial={makeProduct()} categories={null} />);

    await user.click(screen.getByRole('button', { name: 'Delete product' }));
    expect(mocks.deleteProductAction).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm delete product' }));

    expect(mocks.deleteProductAction).toHaveBeenCalledWith('p1');
    expect(mocks.push).toHaveBeenCalledWith('/dashboard/products');
  });

  it('keeps the product and shows the error when deletion fails', async () => {
    const user = userEvent.setup();
    mocks.deleteProductAction.mockResolvedValue({ success: false, error: 'Product not found' });
    render(<ProductEditor initial={makeProduct()} categories={null} />);
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
    render(<ProductEditor initial={base} categories={null} />);

    const price = screen.getByLabelText('Price (USD)');
    await user.clear(price);
    await user.type(price, '19.99');
    await user.click(screen.getByRole('button', { name: /^Save variant/ }));

    expect(await screen.findByText('Variant saved.')).toBeInTheDocument();
    expect(screen.getByLabelText('Price (USD)')).toHaveValue('20.00');
  });

  it('keeps an unsaved title when a variant is saved with a newer product timestamp', async () => {
    const user = userEvent.setup();
    mocks.updateVariantAction.mockResolvedValue({
      success: true,
      data: makeProduct({ updated_at: '2026-03-01T00:00:00Z' }),
    });
    render(<ProductEditor initial={makeProduct()} categories={null} />);

    const title = screen.getByLabelText('Title');
    await user.clear(title);
    await user.type(title, 'Unsaved name');
    await user.click(screen.getByRole('button', { name: /^Save variant/ }));

    expect(await screen.findByText('Variant saved.')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('Unsaved name');
  });

  it('shows "Product saved." after details change the product timestamp', async () => {
    const user = userEvent.setup();
    mocks.updateProductAction.mockResolvedValue({
      success: true,
      data: makeProduct({ status: 'active', updated_at: '2026-03-01T00:00:00Z' }),
    });
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    await user.selectOptions(screen.getByLabelText('Status'), 'active');
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByText('Product saved.')).toBeInTheDocument();
  });

  it('does not submit the product form when Enter is pressed in the category box', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    await user.type(screen.getByLabelText('Category id'), 'cat2{Enter}');
    expect(mocks.updateProductAction).not.toHaveBeenCalled();
    expect(screen.getByText('cat2')).toBeInTheDocument();
  });
});

describe('ProductCreateForm options', () => {
  it('refuses a half-filled option row instead of silently dropping it', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);
    await user.type(screen.getByLabelText('Title'), 'Tee');
    await user.type(screen.getByLabelText('SKU'), 'T');
    await user.type(screen.getByLabelText('Price (USD)'), '5');
    await user.click(screen.getByRole('button', { name: 'Add option' }));
    await user.type(screen.getByLabelText('Option 1 name'), 'Size');
    await user.click(screen.getByRole('button', { name: 'Create product' }));
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Each option needs a name');
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('keeps typed row data when another option value is added', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);
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

describe('CategoriesField with the store category list', () => {
  const list = {
    truncated: false,
    rows: [
      { id: 'c2', name: 'Shirts', slug: 'shirts', parent_id: 'c1', position: 0 },
      { id: 'c1', name: 'Clothing', slug: 'clothing', parent_id: null, position: 0 },
      { id: 'c3', name: 'Mugs', slug: 'mugs', parent_id: null, position: 1 },
    ],
  };

  it('shows names as a tree and toggles a category by checkbox', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<CategoriesField value={['c1']} onChange={onChange} categories={list} />);

    const labels = screen.getAllByRole('checkbox').map((box) => box.parentElement?.textContent);
    expect(labels).toEqual(['Clothing', 'Shirts', 'Mugs']);
    expect(screen.getByLabelText('Clothing')).toBeChecked();

    await user.click(screen.getByLabelText('Mugs'));
    expect(onChange).toHaveBeenCalledWith(['c1', 'c3']);
    await user.click(screen.getByLabelText('Clothing'));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('keeps an unknown linked id visible and removable', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<CategoriesField value={['gone']} onChange={onChange} categories={list} />);
    await user.click(screen.getByLabelText('Unknown category (gone)'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('says so for a store without categories and for a truncated list', () => {
    const { rerender } = render(
      <CategoriesField value={[]} onChange={vi.fn()} categories={{ rows: [], truncated: false }} />
    );
    expect(screen.getByText('This store has no categories yet.')).toBeInTheDocument();
    rerender(
      <CategoriesField value={[]} onChange={vi.fn()} categories={{ ...list, truncated: true }} />
    );
    expect(screen.getByText(/more categories than can be shown/i)).toBeInTheDocument();
  });

  it('saves the chosen category names through the editor', async () => {
    const user = userEvent.setup();
    mocks.updateProductAction.mockResolvedValue({ success: true, data: makeProduct() });
    render(<ProductEditor initial={makeProduct({ category_ids: [] })} categories={list} />);
    await user.click(screen.getByLabelText('Shirts'));
    await user.click(screen.getByRole('button', { name: 'Save details' }));
    expect(mocks.updateProductAction).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ categoryIds: ['c2'] })
    );
  });
});

describe('ProductEditor accessibility', () => {
  it('has one h1 followed by h2 section titles', () => {
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const h2 = screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent);
    expect(h2).toEqual(['Details', 'Variants', 'Images', 'Delete product']);
    expect(screen.queryAllByRole('heading', { level: 3 })).toHaveLength(0);
  });

  it('names each variant button by its variant', () => {
    const withTwo = makeProduct({
      options: [sizeOption],
      variants: [
        {
          ...makeProduct().variants[0],
          option_values: [{ option_id: 'o1', option_value_id: 'ov1' }],
        },
        {
          ...makeProduct().variants[0],
          id: 'v2',
          sku: 'TEE-2',
          option_values: [{ option_id: 'o1', option_value_id: 'ov2' }],
        },
      ],
    });
    render(<ProductEditor initial={withTwo} categories={null} />);
    expect(screen.getByRole('button', { name: 'Save variant: S' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete variant: M' })).toBeInTheDocument();
  });

  it('announces a field error with role alert', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    const price = screen.getByLabelText('Price (USD)');
    await user.clear(price);
    await user.type(price, 'abc');
    await user.click(screen.getByRole('button', { name: /^Save variant/ }));
    expect(screen.getByText('Enter a price like 12.50')).toHaveAttribute('role', 'alert');
  });

  it('announces an added variant with role status', async () => {
    const user = userEvent.setup();
    const withOptions = makeProduct({ options: [sizeOption] });
    mocks.addVariantAction.mockResolvedValue({ success: true, data: withOptions });
    render(<ProductEditor initial={withOptions} categories={null} />);
    const form = screen.getByRole('form', { name: 'Add variant' });
    await user.selectOptions(within(form).getByLabelText('Size'), 'M');
    await user.type(within(form).getByLabelText('SKU'), 'TEE-M');
    await user.type(within(form).getByLabelText('Price (USD)'), '13');
    await user.click(within(form).getByRole('button', { name: 'Add variant' }));
    expect(await within(form).findByRole('status')).toHaveTextContent('Variant added.');
  });

  it('moves focus to Confirm, back to the trigger on Cancel, and cancels on Escape', async () => {
    const user = userEvent.setup();
    render(<ProductEditor initial={makeProduct()} categories={null} />);
    await user.click(screen.getByRole('button', { name: 'Delete product' }));
    expect(screen.getByRole('button', { name: 'Confirm delete product' })).toHaveFocus();

    const group = screen.getByRole('group', { name: 'Delete product' });
    await user.click(within(group).getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Delete product' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Delete product' }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: 'Delete product' })).toHaveFocus();
    expect(mocks.deleteProductAction).not.toHaveBeenCalled();
  });
});

describe('ProductCreateForm variants and option names', () => {
  type User = ReturnType<typeof userEvent.setup>;

  async function addOption(user: User, index: number, name: string, values: string) {
    await user.click(screen.getByRole('button', { name: 'Add option' }));
    await user.type(screen.getByLabelText(`Option ${index} name`), name);
    await user.click(screen.getByLabelText(`Option ${index} values`));
    await user.paste(values);
  }

  it('shows an error and no rows when the options make more than 100 variants', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);
    const many = Array.from({ length: 11 }, (_, i) => `v${i}`).join(',');
    await addOption(user, 1, 'A', many);
    await addOption(user, 2, 'B', many);
    expect(screen.queryAllByTestId('variant-row')).toHaveLength(0);
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('121 variants');

    await user.type(screen.getByLabelText('Title'), 'Tee');
    await user.click(screen.getByRole('button', { name: 'Create product' }));
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('rejects option names that differ only by case', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);
    await addOption(user, 1, 'Size', 'S');
    await addOption(user, 2, 'size', 'M');
    await user.type(screen.getByLabelText('Title'), 'Tee');
    await user.click(screen.getByRole('button', { name: 'Create product' }));
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('different name');
    expect(mocks.createProductAction).not.toHaveBeenCalled();
  });

  it('keeps typed variant data when an option is renamed or a later value is added', async () => {
    const user = userEvent.setup();
    render(<ProductCreateForm currency="USD" categories={null} />);
    await addOption(user, 1, 'Size', 'S');
    await user.type(screen.getByLabelText('SKU'), 'E-S');

    await user.clear(screen.getByLabelText('Option 1 name'));
    await user.type(screen.getByLabelText('Option 1 name'), 'Length');
    expect(screen.getByLabelText('SKU')).toHaveValue('E-S');

    await user.type(screen.getByLabelText('Option 1 values'), ', M');
    const first = screen.getAllByTestId('variant-row')[0];
    expect(within(first).getByLabelText('SKU')).toHaveValue('E-S');
  });
});
