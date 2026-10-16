import type { ChecklistStep, KpiCell } from './types';

/** No merchant data API exists yet, so every store is a new store: dashes, never invented figures. */
export const NEW_STORE_KPI_CELLS: ReadonlyArray<KpiCell> = [
  { id: 'revenue', label: 'Revenue', state: 'empty', emptyText: 'No sales yet' },
  { id: 'orders', label: 'Orders', state: 'empty', emptyText: 'No sales yet' },
  { id: 'conversion', label: 'Conversion', state: 'empty', emptyText: 'No sales yet' },
  { id: 'aov', label: 'Average order', state: 'empty', emptyText: 'No sales yet' },
];

/** Products, Stripe and Domains have no pages yet, so no step links anywhere. */
export const NEW_STORE_CHECKLIST: ReadonlyArray<ChecklistStep> = [
  {
    id: 'product',
    title: 'Add a product',
    description: 'List what you sell so customers can order it.',
  },
  {
    id: 'stripe',
    title: 'Connect Stripe',
    description: 'Take card payments straight to your account.',
  },
  {
    id: 'domain',
    title: 'Add a domain',
    description: 'Point your own web address at your store.',
  },
];
