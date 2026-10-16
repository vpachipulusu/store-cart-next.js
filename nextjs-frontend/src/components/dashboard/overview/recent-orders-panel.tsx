import Link from 'next/link';

import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { Panel } from './panel';
import { RefreshButton } from './refresh-button';
import type { ChecklistStep, OrderStatus, OrdersPanelState, OverviewOrder } from './types';

const STATUS_PILL: Record<OrderStatus, { variant: StatusPillVariant; label: string }> = {
  paid: { variant: 'good', label: 'Paid' },
  pending: { variant: 'warn', label: 'Pending' },
  refunded: { variant: 'neutral', label: 'Refunded' },
  failed: { variant: 'crit', label: 'Failed' },
};

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString();
}

function Checklist({ steps }: { steps: ReadonlyArray<ChecklistStep> }) {
  const next = steps.find((step) => step.href);

  return (
    <div>
      <ol aria-label="Set up your store" className="space-y-3">
        {steps.map((step, index) => (
          <li key={step.id} className="flex gap-3">
            <span
              aria-hidden="true"
              className="font-display text-lg font-semibold tabular-nums text-accent-ink"
            >
              {String(index + 1).padStart(2, '0')}
            </span>
            <div>
              <p className="text-sm font-medium text-foreground">{step.title}</p>
              <p className="text-[0.8125rem] text-muted-foreground">{step.description}</p>
            </div>
          </li>
        ))}
      </ol>
      {next?.href ? (
        <Link
          href={next.href}
          className={cn(buttonVariants({ variant: 'accent' }), 'mt-4 min-h-11')}
        >
          {next.title}
        </Link>
      ) : null}
    </div>
  );
}

function OrdersTable({ orders }: { orders: ReadonlyArray<OverviewOrder> }) {
  return (
    <Table stacked aria-label="Recent orders">
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead>Customer</TableHead>
          <TableHead>Date</TableHead>
          <TableHead>Total</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => {
          const pill = STATUS_PILL[order.status];
          return (
            <TableRow key={order.id}>
              <TableCell label="Order">{order.number}</TableCell>
              <TableCell label="Customer">{order.customer}</TableCell>
              <TableCell label="Date">{formatDate(order.placedAt)}</TableCell>
              <TableCell label="Total" className="tabular-nums">
                {order.total}
              </TableCell>
              <TableCell label="Status">
                <StatusPill variant={pill.variant}>{pill.label}</StatusPill>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function PanelBody({
  state,
  checklist,
}: {
  state: OrdersPanelState;
  checklist: ReadonlyArray<ChecklistStep>;
}) {
  switch (state.status) {
    case 'loading':
      return (
        <div className="space-y-3">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-8 w-full" />
          ))}
        </div>
      );
    case 'error':
      return (
        <div>
          <p role="alert" className="text-sm font-medium text-crit-foreground">
            Could not load orders
          </p>
          <RefreshButton label="Retry" ariaLabel="Retry orders" />
        </div>
      );
    case 'empty':
      return <Checklist steps={checklist} />;
    case 'ready':
      return <OrdersTable orders={state.orders} />;
  }
}

interface RecentOrdersPanelProps {
  state: OrdersPanelState;
  /** Shown instead of the table while the store has no orders. */
  checklist: ReadonlyArray<ChecklistStep>;
}

export function RecentOrdersPanel({ state, checklist }: RecentOrdersPanelProps) {
  return (
    <Panel title="Recent orders" titleId="recent-orders-title" busy={state.status === 'loading'}>
      <PanelBody state={state} checklist={checklist} />
    </Panel>
  );
}
