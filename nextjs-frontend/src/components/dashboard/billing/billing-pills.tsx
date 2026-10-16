import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';

interface PillSpec {
  variant: StatusPillVariant;
  label: string;
}

function humanise(value: string): string {
  const text = value.replace(/_/g, ' ').trim().toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Unknown';
}

/** Maps the backend `subscription_status` to a pill; unknown states stay neutral, never green. */
export function subscriptionPill(status: string | undefined, isActive: boolean): PillSpec {
  if (isActive) return { variant: 'good', label: 'Active' };
  switch (status) {
    case 'trialing':
      return { variant: 'info', label: 'Trial' };
    case 'past_due':
    case 'unpaid':
      return { variant: 'crit', label: 'Payment past due' };
    case 'canceled':
      return { variant: 'neutral', label: 'Canceled' };
    case undefined:
    case '':
    case 'inactive':
      return { variant: 'neutral', label: 'Inactive' };
    default:
      return { variant: 'neutral', label: humanise(status) };
  }
}

/** Maps a Stripe invoice status to a pill. */
export function invoicePill(status: string): PillSpec {
  switch (status) {
    case 'paid':
      return { variant: 'good', label: 'Paid' };
    case 'open':
      return { variant: 'warn', label: 'Open' };
    case 'uncollectible':
      return { variant: 'crit', label: 'Uncollectible' };
    default:
      return { variant: 'neutral', label: humanise(status) };
  }
}

export function SubscriptionStatusPill({
  status,
  isActive,
}: {
  status: string | undefined;
  isActive: boolean;
}) {
  const { variant, label } = subscriptionPill(status, isActive);
  return <StatusPill variant={variant}>{label}</StatusPill>;
}

export function InvoiceStatusPill({ status }: { status: string }) {
  const { variant, label } = invoicePill(status);
  return <StatusPill variant={variant}>{label}</StatusPill>;
}
