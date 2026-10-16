import type { UsageMeterItem } from '@/components/dashboard/plan-usage-meter';

/**
 * Sample plan-usage figures. There is no plan-usage API yet, so the billing page shows these
 * (labelled as samples) until a real source exists. Limits are illustrative, not enforced.
 */
export const PLAN_USAGE_FIXTURES: Readonly<Record<string, ReadonlyArray<UsageMeterItem>>> = {
  free: [
    { id: 'stores', label: 'Stores', used: 0, limit: 1 },
    { id: 'products', label: 'Products', used: 0, limit: 25 },
    { id: 'staff', label: 'Staff accounts', used: 0, limit: 1 },
  ],
  pro: [
    { id: 'stores', label: 'Stores', used: 0, limit: 5 },
    { id: 'products', label: 'Products', used: 0, limit: null },
    { id: 'staff', label: 'Staff accounts', used: 0, limit: 5 },
  ],
  enterprise: [
    { id: 'stores', label: 'Stores', used: 0, limit: null },
    { id: 'products', label: 'Products', used: 0, limit: null },
    { id: 'staff', label: 'Staff accounts', used: 0, limit: null },
  ],
};

export function planUsageFixture(tier: string | undefined): UsageMeterItem[] {
  const items = PLAN_USAGE_FIXTURES[tier ?? 'free'] ?? PLAN_USAGE_FIXTURES.free;
  return [...items];
}
