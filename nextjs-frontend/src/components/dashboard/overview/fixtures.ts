import type { AttentionItem, OverviewOrder } from './types';

/** Typed sample data for tests and design review. The live page never renders these. */
export const SAMPLE_ORDERS: ReadonlyArray<OverviewOrder> = [
  {
    id: 'o1',
    number: '#1042',
    customer: 'Ada Lovelace',
    placedAt: '2026-10-14T09:30:00Z',
    total: '£48.00',
    status: 'paid',
  },
  {
    id: 'o2',
    number: '#1041',
    customer: 'Grace Hopper',
    placedAt: '2026-10-13T16:05:00Z',
    total: '£120.50',
    status: 'pending',
  },
  {
    id: 'o3',
    number: '#1040',
    customer: 'Alan Turing',
    placedAt: '2026-10-12T11:20:00Z',
    total: '£19.99',
    status: 'refunded',
  },
];

export const SAMPLE_ATTENTION: ReadonlyArray<AttentionItem> = [
  {
    id: 'unfulfilled',
    label: 'Orders to fulfil',
    count: 3,
    actionLabel: 'Review',
    href: '/dashboard',
  },
];
