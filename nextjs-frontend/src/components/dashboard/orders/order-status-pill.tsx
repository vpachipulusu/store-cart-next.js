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
  // An unknown status (a newer backend) still renders, neutral and with its raw text.
  return (
    <StatusPill variant={VARIANTS[status] ?? 'neutral'}>
      {ORDER_STATUS_LABELS[status] ?? status}
    </StatusPill>
  );
}
