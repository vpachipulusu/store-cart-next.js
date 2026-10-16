import type { KpiCell } from '@/components/dashboard/kpi-strip';

export type { KpiCell };

export type OrderStatus = 'paid' | 'pending' | 'refunded' | 'failed';

/** One row of the recent-orders table. Strings arrive already formatted; the merchant API will supply them. */
export interface OverviewOrder {
  id: string;
  number: string;
  customer: string;
  /** ISO timestamp. */
  placedAt: string;
  total: string;
  status: OrderStatus;
}

export type OrdersPanelState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'empty' }
  | { status: 'ready'; orders: ReadonlyArray<OverviewOrder> };

export interface AttentionItem {
  id: string;
  label: string;
  count: number;
  /** Verb phrase for the link, e.g. "Review". */
  actionLabel: string;
  href: string;
}

export interface ChecklistStep {
  id: string;
  title: string;
  description: string;
  /** Omitted while the destination page does not exist yet. */
  href?: string;
}
