import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { invoicePill, subscriptionPill } from '@/components/dashboard/billing/billing-pills';
import { InvoiceTable, formatAmount } from '@/components/dashboard/billing/invoice-table';

describe('subscriptionPill', () => {
  it('is good only for an active subscription', () => {
    expect(subscriptionPill('active', true)).toEqual({ variant: 'good', label: 'Active' });
  });

  it.each([
    ['trialing', 'info', 'Trial'],
    ['unpaid', 'crit', 'Payment past due'],
    ['past_due', 'crit', 'Payment past due'],
    ['canceled', 'neutral', 'Canceled'],
    ['incomplete_expired', 'neutral', 'Incomplete expired'],
  ])('maps %s to %s without going green', (status, variant, label) => {
    expect(subscriptionPill(status, false)).toEqual({ variant, label });
  });

  it('keeps an unrecognised status neutral even when it says active but is not entitled', () => {
    expect(subscriptionPill('active', false).variant).toBe('neutral');
  });
});

describe('invoicePill', () => {
  it.each([
    ['paid', 'good', 'Paid'],
    ['open', 'warn', 'Open'],
    ['uncollectible', 'crit', 'Uncollectible'],
    ['void', 'neutral', 'Void'],
    ['something_new', 'neutral', 'Something new'],
  ])('maps %s to %s', (status, variant, label) => {
    expect(invoicePill(status)).toEqual({ variant, label });
  });
});

const BASE = {
  id: 'in_1',
  amount: 1000,
  currency: 'usd',
  status: 'paid',
  created: '2026-11-01T00:00:00Z',
  pdfUrl: null,
  hostedUrl: null,
};

describe('InvoiceTable links', () => {
  it('renders no link for http:// or javascript: urls', () => {
    render(
      <InvoiceTable
        invoices={[
          { ...BASE, pdfUrl: 'http://example.test/a.pdf', hostedUrl: 'javascript:alert(1)' },
        ]}
      />
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders https links whose names include the amount so same-day invoices differ', () => {
    render(
      <InvoiceTable
        invoices={[
          { ...BASE, pdfUrl: 'https://example.test/a.pdf' },
          { ...BASE, id: 'in_2', amount: 2500, pdfUrl: 'https://example.test/b.pdf' },
        ]}
      />
    );

    expect(screen.getByRole('link', { name: /\$10\.00/ })).toHaveAttribute(
      'href',
      'https://example.test/a.pdf'
    );
    expect(screen.getByRole('link', { name: /\$25\.00/ })).toHaveAttribute(
      'href',
      'https://example.test/b.pdf'
    );
  });
});

describe('formatAmount', () => {
  it('formats a known currency', () => {
    expect(formatAmount(2900, 'usd')).toBe('$29.00');
  });

  it('falls back to the plain number for an invalid currency code instead of throwing', () => {
    expect(formatAmount(1000, 'not-a-code')).toBe('10.00 NOT-A-CODE');
  });
});
