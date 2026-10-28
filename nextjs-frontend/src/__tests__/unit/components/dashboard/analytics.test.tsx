/** KAN-96: the analytics report, its chart, tables and the role and empty states. */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import {
  AnalyticsReport,
  AnalyticsRoleNotice,
} from '@/components/dashboard/analytics/analytics-report';
import { AnalyticsRangeForm } from '@/components/dashboard/analytics/analytics-range-form';
import { SalesChart } from '@/components/dashboard/analytics/sales-chart';
import type { CurrencyAnalyticsData, StoreAnalyticsData } from '@/lib/api/analytics';

function point(day: string, orders: number, gross: number, refunds: number) {
  return {
    bucket_start: day,
    orders,
    gross_sales_minor: gross,
    refunds_minor: refunds,
    net_sales_minor: gross - refunds,
  };
}

const gbp: CurrencyAnalyticsData = {
  currency: 'GBP',
  totals: { orders: 3, gross_sales_minor: 7500, refunds_minor: 1000, net_sales_minor: 6500 },
  series: [
    point('2026-10-01', 2, 5000, 1000),
    point('2026-10-02', 0, 0, 0),
    point('2026-10-03', 1, 2500, 0),
  ],
  top_products_by_revenue: [
    { product_name: 'Lamp', units: 1, revenue_minor: 5000 },
    { product_name: 'Mug', units: 3, revenue_minor: 2500 },
  ],
  top_products_by_units: [
    { product_name: 'Mug', units: 3, revenue_minor: 2500 },
    { product_name: 'Lamp', units: 1, revenue_minor: 5000 },
  ],
};

const jpy: CurrencyAnalyticsData = {
  currency: 'JPY',
  totals: { orders: 1, gross_sales_minor: 1500, refunds_minor: 0, net_sales_minor: 1500 },
  series: [
    point('2026-10-01', 0, 0, 0),
    point('2026-10-02', 1, 1500, 0),
    point('2026-10-03', 0, 0, 0),
  ],
  top_products_by_revenue: [],
  top_products_by_units: [],
};

function report(currencies: CurrencyAnalyticsData[]): StoreAnalyticsData {
  return { start_date: '2026-10-01', end_date: '2026-10-03', bucket: 'day', currencies };
}

describe('AnalyticsReport', () => {
  it('shows each currency with its own totals, never converted', () => {
    render(<AnalyticsReport report={report([gbp, jpy])} />);

    const pounds = screen.getByTestId('analytics-GBP');
    expect(within(pounds).getByRole('group', { name: 'Net sales' })).toHaveTextContent('£65.00');
    expect(within(pounds).getByRole('group', { name: 'Gross sales' })).toHaveTextContent('£75.00');
    expect(within(pounds).getByRole('group', { name: 'Refunds' })).toHaveTextContent('£10.00');
    expect(within(pounds).getByRole('group', { name: 'Orders' })).toHaveTextContent('3');
    // Yen has no minor unit: 1500 is ¥1,500.
    const yen = screen.getByTestId('analytics-JPY');
    expect(within(yen).getByRole('group', { name: 'Net sales' })).toHaveTextContent('¥1,500');
  });

  it('lists every bucket, empty ones included, in the accessible table', () => {
    render(<AnalyticsReport report={report([gbp])} />);

    const table = screen.getByRole('table', { name: 'Daily sales in GBP' });
    const rows = within(table).getAllByTestId('sales-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('1 Oct');
    expect(rows[0]).toHaveTextContent('£50.00');
    expect(rows[0]).toHaveTextContent('£40.00');
    expect(rows[1]).toHaveTextContent('£0.00');
  });

  it('ranks top products by revenue and by units', () => {
    render(<AnalyticsReport report={report([gbp])} />);

    const byRevenue = screen.getByRole('table', { name: 'Top products by revenue' });
    const byUnits = screen.getByRole('table', { name: 'Top products by units' });
    expect(within(byRevenue).getAllByTestId('top-product-row')[0]).toHaveTextContent('Lamp');
    expect(within(byUnits).getAllByTestId('top-product-row')[0]).toHaveTextContent('Mug');
  });

  it('says when a currency sold no products', () => {
    render(<AnalyticsReport report={report([jpy])} />);

    expect(screen.getAllByText('No products sold in this period.')).toHaveLength(2);
  });

  it('has an empty state for a range without sales', () => {
    render(<AnalyticsReport report={report([])} />);

    expect(screen.getByRole('status')).toHaveTextContent('No sales in this period.');
  });
});

describe('SalesChart', () => {
  it('draws one bar per bucket, scaled to the best one, hidden from assistive technology', () => {
    render(<SalesChart series={gbp.series} currency="GBP" bucket="day" />);

    const chart = screen.getByTestId('sales-chart-GBP');
    expect(chart).toHaveAttribute('aria-hidden', 'true');
    const bars = within(chart).getAllByTestId('sales-bar');
    expect(bars.map((bar) => bar.style.height)).toEqual(['100%', '0%', '62.5%']);
    expect(bars[0]).toHaveAttribute('title', '1 Oct: £40.00');
  });
});

describe('AnalyticsRangeForm', () => {
  it('is a GET form prefilled with the applied range and bucket', () => {
    render(<AnalyticsRangeForm from="2026-10-01" to="2026-10-03" bucket="week" />);

    const form = screen.getByRole('form', { name: 'Analytics range' });
    expect(form).toHaveAttribute('method', 'get');
    expect(screen.getByLabelText('From')).toHaveValue('2026-10-01');
    expect(screen.getByLabelText('To')).toHaveValue('2026-10-03');
    expect(screen.getByLabelText('Group by')).toHaveValue('week');
    expect(screen.getByRole('link', { name: 'Last 30 days' })).toHaveAttribute(
      'href',
      '/dashboard/analytics'
    );
  });
});

describe('AnalyticsRoleNotice', () => {
  it('explains that the role cannot see analytics', () => {
    render(<AnalyticsRoleNotice />);

    expect(screen.getByTestId('analytics-forbidden')).toHaveTextContent(
      'Analytics are not available for your role.'
    );
  });
});
