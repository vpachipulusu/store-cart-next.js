import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const refresh = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));

import { OverviewKpiStrip } from '@/components/dashboard/overview/overview-kpi-strip';
import { OverviewPlanUsage } from '@/components/dashboard/overview/overview-plan-usage';
import { RecentOrdersPanel } from '@/components/dashboard/overview/recent-orders-panel';
import { NeedsAttention } from '@/components/dashboard/overview/needs-attention';
import { PermissionNotice } from '@/components/dashboard/overview/permission-notice';
import { NEW_STORE_KPI_CELLS, NEW_STORE_CHECKLIST } from '@/components/dashboard/overview/defaults';
import { SAMPLE_ORDERS, SAMPLE_ATTENTION } from '@/components/dashboard/overview/fixtures';

beforeEach(() => refresh.mockClear());

describe('OverviewKpiStrip', () => {
  it('shows the new-store cells as dashes with "No sales yet"', () => {
    render(<OverviewKpiStrip cells={NEW_STORE_KPI_CELLS} />);

    expect(screen.getAllByText('No sales yet')).toHaveLength(4);
    expect(screen.getByRole('group', { name: 'Revenue' })).toBeInTheDocument();
  });

  it('wires the retry button of an errored cell to a router refresh', async () => {
    render(<OverviewKpiStrip cells={[{ id: 'revenue', label: 'Revenue', state: 'error' }]} />);

    await userEvent.click(screen.getByRole('button', { name: 'Retry Revenue' }));

    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe('OverviewPlanUsage', () => {
  it('shows the meters and a Compare plans link', () => {
    render(
      <OverviewPlanUsage
        items={[{ id: 'stores', label: 'Stores', used: 1, limit: 3 }]}
        compareHref="/pricing"
      />
    );

    expect(screen.getByRole('meter', { name: 'Stores' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Compare plans' })).toHaveAttribute('href', '/pricing');
  });

  it('strips the meter surface so it does not nest a card in the Plan panel', () => {
    render(<OverviewPlanUsage items={[]} compareHref="/pricing" />);

    expect(screen.getByRole('group', { name: 'Plan usage' })).toHaveClass('border-0', 'p-0');
    expect(screen.getByRole('group', { name: 'Plan usage' })).not.toHaveClass('border');
  });

  it('retries through a router refresh when it failed to load', async () => {
    render(<OverviewPlanUsage items={[]} state="error" compareHref="/pricing" />);

    await userEvent.click(screen.getByRole('button', { name: 'Retry plan usage' }));

    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe('RecentOrdersPanel', () => {
  it('is titled by an h2', () => {
    render(<RecentOrdersPanel state={{ status: 'empty' }} checklist={NEW_STORE_CHECKLIST} />);

    expect(screen.getByRole('heading', { level: 2, name: 'Recent orders' })).toBeInTheDocument();
  });

  it('replaces the table with a three-step checklist for a new store', () => {
    render(<RecentOrdersPanel state={{ status: 'empty' }} checklist={NEW_STORE_CHECKLIST} />);

    const list = screen.getByRole('list', { name: 'Set up your store' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(within(list).getByText('Add a product')).toBeInTheDocument();
    expect(within(list).getByText('Connect Stripe')).toBeInTheDocument();
    expect(within(list).getByText('Add a domain')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows one accent action only when the next step has a destination', () => {
    const { rerender } = render(
      <RecentOrdersPanel state={{ status: 'empty' }} checklist={NEW_STORE_CHECKLIST} />
    );
    expect(screen.queryByRole('link', { name: /add a product/i })).not.toBeInTheDocument();

    rerender(
      <RecentOrdersPanel
        state={{ status: 'empty' }}
        checklist={[
          { id: 'product', title: 'Add a product', description: 'x', href: '/dashboard/products' },
          ...NEW_STORE_CHECKLIST.slice(1),
        ]}
      />
    );
    expect(screen.getByRole('link', { name: 'Add a product' })).toHaveAttribute(
      'href',
      '/dashboard/products'
    );
  });

  it('renders orders in a real table with status pills as icon plus text', () => {
    render(<RecentOrdersPanel state={{ status: 'ready', orders: SAMPLE_ORDERS }} checklist={[]} />);

    const table = screen.getByRole('table', { name: 'Recent orders' });
    expect(within(table).getAllByRole('row')).toHaveLength(SAMPLE_ORDERS.length + 1);
    expect(within(table).getByText(SAMPLE_ORDERS[0].customer)).toBeInTheDocument();
    // No orders route exists yet, so there is no self-linking "View all orders".
    expect(screen.queryByRole('link', { name: 'View all orders' })).not.toBeInTheDocument();
  });

  it('shows skeletons while loading', () => {
    render(<RecentOrdersPanel state={{ status: 'loading' }} checklist={[]} />);

    expect(screen.getByRole('region', { name: 'Recent orders' })).toHaveAttribute(
      'aria-busy',
      'true'
    );
  });

  it('shows "Could not load orders" with a retry that refreshes', async () => {
    render(<RecentOrdersPanel state={{ status: 'error' }} checklist={[]} />);

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load orders');
    await userEvent.click(screen.getByRole('button', { name: 'Retry orders' }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe('NeedsAttention', () => {
  it('says nothing needs attention when the list is empty', () => {
    render(<NeedsAttention items={[]} />);

    expect(screen.getByRole('heading', { level: 2, name: 'Needs attention' })).toBeInTheDocument();
    expect(screen.getByText('Nothing needs attention')).toBeInTheDocument();
  });

  it('lists items with a count pill and a verb link', () => {
    render(<NeedsAttention items={SAMPLE_ATTENTION} />);

    const first = SAMPLE_ATTENTION[0];
    const row = screen.getAllByRole('listitem')[0];
    expect(within(row).getByText(String(first.count))).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: new RegExp(first.actionLabel) })).toHaveAttribute(
      'href',
      first.href
    );
  });
});

describe('PermissionNotice', () => {
  it('names the owner and links back to Overview', () => {
    render(<PermissionNotice ownerName="Priya" />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'You do not have access. Ask the owner (Priya) for the role'
    );
    expect(screen.getByRole('link', { name: 'Back to Overview' })).toHaveAttribute(
      'href',
      '/dashboard'
    );
  });

  it('omits the owner name when unknown', () => {
    render(<PermissionNotice />);

    expect(screen.getByRole('alert')).toHaveTextContent('Ask the owner for the role');
  });
});
