export interface PlanStatusInput {
  /** Plan key the organisation is entitled to (free, pro, enterprise). */
  planKey: string;
  /** Backend `subscription_status` value. */
  status: string;
  /** Renewal or trial end (ISO), when the backend knows it. */
  periodEnd: string | null;
  /** Whether a Stripe subscription backs the plan; a paid plan without one was granted by an admin. */
  hasSubscription: boolean;
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString();
}

function humanise(status: string): string {
  const text = status.replace(/_/g, ' ').trim().toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Unknown';
}

/**
 * The line under the plan name on the dashboard. Driven by the backend's effective plan and
 * `subscription_status`: the backend entitles active, trialing and past_due, and an admin-granted plan
 * has a paid plan key, no Stripe subscription and status inactive.
 */
export function describePlanStatus({
  planKey,
  status,
  periodEnd,
  hasSubscription,
}: PlanStatusInput): string {
  if (planKey !== 'free' && !hasSubscription) {
    return 'Granted by admin';
  }
  const date = formatDate(periodEnd);
  switch (status) {
    case 'active':
      return date ? `Active until ${date}` : 'Active';
    case 'trialing':
      return date ? `Trial ends ${date}` : 'Trial';
    case 'past_due':
      return 'Payment past due';
    default:
      return humanise(status);
  }
}
