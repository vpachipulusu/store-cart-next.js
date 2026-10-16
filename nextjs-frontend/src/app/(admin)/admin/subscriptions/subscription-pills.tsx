import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';

const STATUS_VARIANTS: Record<string, StatusPillVariant> = {
  active: 'good',
  trialing: 'good',
  past_due: 'warn',
  unpaid: 'warn',
  incomplete: 'warn',
};

function sentenceCase(value: string): string {
  const spaced = value.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function PlanPill({ plan }: { plan: string }) {
  return <StatusPill variant="info">{sentenceCase(plan)}</StatusPill>;
}

export function SubscriptionStatusPill({ status }: { status: string }) {
  return (
    <StatusPill variant={STATUS_VARIANTS[status] ?? 'neutral'}>{sentenceCase(status)}</StatusPill>
  );
}
