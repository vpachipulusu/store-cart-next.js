/** KAN-75: the storefront's interactive pieces: option picking and add to basket, the basket, the header count. */
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  readCart: vi.fn(),
  addToCart: vi.fn(),
  setQuantity: vi.fn(),
  removeLine: vi.fn(),
}));

vi.mock('@/lib/storefront/cart-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/storefront/cart-client')>(
    '@/lib/storefront/cart-client'
  );
  return { ...actual, ...mocks };
});

import { AddToCart, parseQuantity } from '@/components/storefront/add-to-cart';
import { BasketView } from '@/components/storefront/basket-view';
import { CartCount } from '@/components/storefront/cart-count';
import { CART_CHANGED_EVENT, type Cart } from '@/lib/storefront/cart-client';
import type { ProductOption, ProductVariant } from '@/lib/storefront/catalogue';

const options: ProductOption[] = [
  {
    name: 'Size',
    values: [
      { id: 'small', value: 'Small' },
      { id: 'medium', value: 'Medium' },
    ],
  },
];
const variants: ProductVariant[] = [
  {
    id: 'v-s',
    priceMinor: 1250,
    compareAtPriceMinor: null,
    inStock: false,
    optionValueIds: ['small'],
  },
  {
    id: 'v-m',
    priceMinor: 1450,
    compareAtPriceMinor: 1800,
    inStock: true,
    optionValueIds: ['medium'],
  },
];

function cartWith(quantity: number): Cart {
  const lines =
    quantity === 0
      ? []
      : [
          {
            variant_id: 'v-m',
            product_id: 'p1',
            product_name: 'Blue Mug',
            product_slug: 'blue-mug',
            sku: 'X',
            variant_label: 'Medium',
            unit_price_minor: 1450,
            quantity,
            line_total_minor: 1450 * quantity,
            available_stock: 9,
            status: 'ok' as const,
          },
        ];
  return {
    lines,
    subtotal_minor: 1450 * quantity,
    shipping_minor: 0,
    tax_minor: 0,
    total_minor: 1450 * quantity,
    prices_include_tax: true,
    can_checkout: quantity > 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('parseQuantity', () => {
  it.each([
    ['3', 3],
    ['0', 1],
    ['', 1],
    ['2.5', 1],
    ['150', 99],
    ['abc', 1],
  ])('%j is %s', (text, expected) => {
    expect(parseQuantity(text)).toBe(expected);
  });
});

describe('AddToCart', () => {
  it('starts on the in-stock variant with its price and sale price', () => {
    render(<AddToCart options={options} variants={variants} currency="GBP" />);

    expect(screen.getByRole('radio', { name: 'Medium' })).toBeChecked();
    expect(screen.getByText('£14.50')).toBeInTheDocument();
    expect(screen.getByText('£18.00')).toBeInTheDocument();
    expect(screen.getByText('In stock')).toBeInTheDocument();
  });

  it('blocks an out-of-stock choice without taking the button out of the tab order', async () => {
    const user = userEvent.setup();
    render(<AddToCart options={options} variants={variants} currency="GBP" />);

    await user.click(screen.getByText('Small'));
    const button = screen.getByRole('button', { name: 'Add to basket' });
    await user.click(button);

    expect(screen.getByText('Out of stock')).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).not.toHaveAttribute('disabled');
    expect(mocks.addToCart).not.toHaveBeenCalled();
  });

  it('adds the chosen variant with a clamped quantity and links to the basket', async () => {
    const user = userEvent.setup();
    mocks.addToCart.mockResolvedValue({ ok: true, cart: cartWith(2) });
    render(<AddToCart options={options} variants={variants} currency="GBP" />);

    const quantity = screen.getByLabelText('Quantity');
    await user.clear(quantity);
    await user.type(quantity, '150');
    await user.click(screen.getByRole('button', { name: 'Add to basket' }));

    expect(mocks.addToCart).toHaveBeenCalledWith('v-m', 99);
    expect(await screen.findByText(/Added to your basket/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View basket' })).toHaveAttribute('href', '/basket');
  });

  it('shows the cart error text', async () => {
    const user = userEvent.setup();
    mocks.addToCart.mockResolvedValue({ ok: false, error: 'Only 1 in stock' });
    render(<AddToCart options={options} variants={variants} currency="GBP" />);

    await user.click(screen.getByRole('button', { name: 'Add to basket' }));

    expect(await screen.findByText('Only 1 in stock')).toBeInTheDocument();
  });

  it('says when a combination does not exist', async () => {
    const user = userEvent.setup();
    render(<AddToCart options={options} variants={[variants[1]]} currency="GBP" />);

    await user.click(screen.getByText('Small'));

    expect(screen.getByText('This combination is not available.')).toBeInTheDocument();
  });
});

describe('BasketView', () => {
  it('lists the line and commits a quantity on Enter, announcing the new total', async () => {
    const user = userEvent.setup();
    mocks.readCart.mockResolvedValue({ ok: true, cart: cartWith(1) });
    mocks.setQuantity.mockResolvedValue({ ok: true, cart: cartWith(3) });
    render(<BasketView currency="GBP" />);

    const quantity = await screen.findByLabelText('Quantity of Blue Mug');
    await user.clear(quantity);
    await user.type(quantity, '3{Enter}');

    expect(mocks.setQuantity).toHaveBeenCalledWith('v-m', 3);
    expect(
      await screen.findByText('Blue Mug quantity is now 3. Total £43.50.')
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Quantity of Blue Mug')).toHaveValue(3);
  });

  it('removes a line, announces it and moves focus to Continue shopping', async () => {
    const user = userEvent.setup();
    mocks.readCart.mockResolvedValue({ ok: true, cart: cartWith(1) });
    mocks.removeLine.mockResolvedValue({ ok: true, cart: cartWith(0) });
    const frame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0);
      return 0;
    });
    render(<BasketView currency="GBP" />);

    await user.click(await screen.findByRole('button', { name: 'Remove Blue Mug' }));

    expect(mocks.removeLine).toHaveBeenCalledWith('v-m');
    expect(await screen.findByText('Your basket is empty.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Removed Blue Mug.');
    frame.mockRestore();
  });

  it('keeps the basket and shows the error when a change fails', async () => {
    const user = userEvent.setup();
    mocks.readCart.mockResolvedValue({ ok: true, cart: cartWith(1) });
    mocks.removeLine.mockResolvedValue({ ok: false, error: 'Too many requests' });
    render(<BasketView currency="GBP" />);

    await user.click(await screen.findByRole('button', { name: 'Remove Blue Mug' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests');
    expect(screen.getByLabelText('Quantity of Blue Mug')).toBeInTheDocument();
  });

  it('puts the quantity back when the update is refused', async () => {
    const user = userEvent.setup();
    mocks.readCart.mockResolvedValue({ ok: true, cart: cartWith(1) });
    mocks.setQuantity.mockResolvedValue({ ok: false, error: 'Only 1 in stock' });
    render(<BasketView currency="GBP" />);

    const quantity = await screen.findByLabelText('Quantity of Blue Mug');
    await user.clear(quantity);
    await user.type(quantity, '5{Enter}');

    expect(await screen.findByRole('alert')).toHaveTextContent('Only 1 in stock');
    expect(screen.getByLabelText('Quantity of Blue Mug')).toHaveValue(1);
  });

  it('offers a retry when the first read fails', async () => {
    const user = userEvent.setup();
    mocks.readCart
      .mockResolvedValueOnce({ ok: false, error: 'The basket could not be updated.' })
      .mockResolvedValueOnce({ ok: true, cart: cartWith(0) });
    render(<BasketView currency="GBP" />);

    await user.click(await screen.findByRole('button', { name: 'Try again' }));

    expect(await screen.findByText('Your basket is empty.')).toBeInTheDocument();
  });
});

describe('CartCount', () => {
  it('shows the count from the cart and follows cart changes', async () => {
    mocks.readCart.mockResolvedValue({ ok: true, cart: cartWith(1) });
    render(<CartCount />);

    expect(await screen.findByRole('link', { name: 'Basket, 1 item' })).toHaveAttribute(
      'href',
      '/basket'
    );
    act(() => {
      window.dispatchEvent(new CustomEvent(CART_CHANGED_EVENT, { detail: cartWith(4) }));
    });
    expect(screen.getByRole('link', { name: 'Basket, 4 items' })).toBeInTheDocument();
  });

  it('ignores a first read that answers after a newer change', async () => {
    let answer: (value: unknown) => void = () => undefined;
    mocks.readCart.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    render(<CartCount />);

    act(() => {
      window.dispatchEvent(new CustomEvent(CART_CHANGED_EVENT, { detail: cartWith(3) }));
    });
    await act(async () => {
      answer({ ok: true, cart: cartWith(0) });
    });

    expect(screen.getByRole('link', { name: 'Basket, 3 items' })).toBeInTheDocument();
  });

  it('shows a plain basket link when the cart cannot be read', async () => {
    mocks.readCart.mockResolvedValue({ ok: false, error: 'down' });
    render(<CartCount />);

    expect(await screen.findByRole('link', { name: 'Basket' })).toBeInTheDocument();
  });
});
