'use client';

import { useRouter } from 'next/navigation';

import { KpiStrip } from '@/components/dashboard/kpi-strip';
import type { KpiCell } from './types';

interface OverviewKpiStripProps {
  cells: ReadonlyArray<KpiCell>;
}

/** Client wrapper: server components cannot pass the retry function KpiStrip needs. */
export function OverviewKpiStrip({ cells }: OverviewKpiStripProps) {
  const router = useRouter();
  const withRetry = cells.map((cell) =>
    cell.state === 'error' ? { ...cell, onRetry: () => router.refresh() } : cell
  );

  return <KpiStrip cells={withRetry} />;
}
