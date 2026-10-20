/** KAN-77: the return pages never mark anything paid, read no query, and the cancel page leads back to the basket. */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// A page that read a cookie, header or query would have to import these: the pages must not.
const dynamicApis = vi.hoisted(() => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('next/headers', () => dynamicApis);

import CheckoutSuccessPage, {
  dynamic as successDynamic,
  metadata as successMetadata,
} from '@/app/storefront/[slug]/checkout/success/page';
import CheckoutCancelPage, {
  dynamic as cancelDynamic,
  metadata as cancelMetadata,
} from '@/app/storefront/[slug]/checkout/cancel/page';

describe('checkout success page', () => {
  it('says the order is being confirmed, not that it is paid', () => {
    render(<CheckoutSuccessPage />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Thank you for your order' })
    ).toBeInTheDocument();
    expect(screen.getByText(/confirming your order/i)).toBeInTheDocument();
    expect(screen.queryByText(/payment received|order (is )?(confirmed|paid)/i)).toBeNull();
    expect(screen.getByRole('link', { name: 'Continue shopping' })).toHaveAttribute('href', '/');
  });

  it('is rendered per request, noindex, and reads no query, cookie or header', () => {
    render(<CheckoutSuccessPage />);

    expect(successDynamic).toBe('force-dynamic');
    expect(successMetadata.title).toBe('Order received');
    expect(successMetadata.robots).toEqual({ index: false, follow: false });
    expect(CheckoutSuccessPage.length).toBe(0);
    expect(dynamicApis.cookies).not.toHaveBeenCalled();
    expect(dynamicApis.headers).not.toHaveBeenCalled();
  });
});

describe('checkout cancel page', () => {
  it('returns the shopper to the basket', () => {
    render(<CheckoutCancelPage />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Checkout cancelled' })
    ).toBeInTheDocument();
    expect(screen.getByText(/not been charged/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to your basket' })).toHaveAttribute(
      'href',
      '/basket'
    );
  });

  it('is rendered per request and noindex', () => {
    expect(cancelDynamic).toBe('force-dynamic');
    expect(cancelMetadata.title).toBe('Checkout cancelled');
    expect(cancelMetadata.robots).toEqual({ index: false, follow: false });
  });
});
