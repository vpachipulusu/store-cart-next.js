'use client';

import { useRouter } from 'next/navigation';

import { PlanUsageMeter, type UsageMeterItem } from '@/components/dashboard/plan-usage-meter';

interface OverviewPlanUsageProps {
  items: ReadonlyArray<UsageMeterItem>;
  state?: 'ready' | 'loading' | 'error';
  compareHref: string;
}

/** Client wrapper: supplies the retry handler and the Compare plans link. */
export function OverviewPlanUsage({ items, state, compareHref }: OverviewPlanUsageProps) {
  const router = useRouter();

  return (
    <PlanUsageMeter
      items={[...items]}
      state={state}
      className="rounded-none border-0 bg-transparent p-0"
      onRetry={() => router.refresh()}
      compareAction={{ label: 'Compare plans', href: compareHref }}
    />
  );
}
