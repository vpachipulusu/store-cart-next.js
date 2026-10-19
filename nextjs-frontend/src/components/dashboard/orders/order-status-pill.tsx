import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';
import { ORDER_STATUS_LABELS, type OrderStatus } from '@/lib/orders/schema';

const VARIANTS: Record<OrderStatus, StatusPillVariant> = {
  pending: 'warn',
  paid: 'info',
  fulfilled: 'good',
  cancelled: 'neutral',
  refunded: 'neutral',
};

/** The order status as a labelled pill; the text carries the meaning, the colour only supports it. */
export function OrderStatusPill({ status }: { status: OrderStatus }) {
  return <StatusPill variant={VARIANTS[status]}>{ORDER_STATUS_LABELS[status]}</StatusPill>;
}
