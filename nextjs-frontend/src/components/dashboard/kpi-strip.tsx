'use client';

import Link from 'next/link';
import { ArrowDown, ArrowUp, Minus } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export type KpiDirection = 'up' | 'down' | 'flat';

export interface KpiDelta {
  direction: KpiDirection;
  /** Visible magnitude, e.g. "12%". */
  text: string;
  /** What it is compared with, e.g. "the previous 7 days". Spoken, not shown. */
  comparison: string;
}

interface KpiCellBase {
  id: string;
  label: string;
}

export interface KpiReadyCell extends KpiCellBase {
  state: 'ready';
  value: string;
  /** Omit or pass null when the previous period has no data. */
  delta?: KpiDelta | null;
  /** Decorative series for the sparkline; needs at least two points. */
  trend?: number[];
}

export interface KpiLoadingCell extends KpiCellBase {
  state: 'loading';
}

export interface KpiEmptyCell extends KpiCellBase {
  state: 'empty';
  emptyText?: string;
  emptyAction?: { label: string; href: string };
}

export interface KpiErrorCell extends KpiCellBase {
  state: 'error';
  onRetry?: () => void;
}

export type KpiCell = KpiReadyCell | KpiLoadingCell | KpiEmptyCell | KpiErrorCell;

export interface KpiStripProps {
  cells: KpiCell[];
  className?: string;
}

const DELTA_STYLES: Record<KpiDirection, { icon: typeof ArrowUp; tone: string; spoken: string }> = {
  up: { icon: ArrowUp, tone: 'text-good-foreground', spoken: 'up' },
  down: { icon: ArrowDown, tone: 'text-crit-foreground', spoken: 'down' },
  flat: { icon: Minus, tone: 'text-muted-foreground', spoken: 'no change' },
};

const ACTION_CLASS =
  'inline-flex min-h-11 items-center rounded-md px-1 text-sm font-semibold text-accent-ink underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-ring';

const SPARK_WIDTH = 120;
const SPARK_HEIGHT = 28;
const SPARK_PADDING = 2;

function sparklinePath(points: number[]): string {
  const min = Math.min(...points);
  const range = Math.max(...points) - min;
  const step = SPARK_WIDTH / (points.length - 1);
  const drawable = SPARK_HEIGHT - SPARK_PADDING * 2;

  return points
    .map((point, index) => {
      const y =
        range === 0
          ? SPARK_HEIGHT / 2
          : SPARK_HEIGHT - SPARK_PADDING - ((point - min) / range) * drawable;
      return `${index === 0 ? 'M' : 'L'}${(index * step).toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
}

function Sparkline({ id, points }: { id: string; points: number[] }) {
  return (
    <svg
      data-testid={`kpi-sparkline-${id}`}
      aria-hidden="true"
      focusable="false"
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      className="mt-2 h-7 w-full max-w-[7.5rem] text-muted-foreground"
    >
      <path d={sparklinePath(points)} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Delta({ delta }: { delta?: KpiDelta | null }) {
  if (!delta) {
    return <p className="mt-1 text-[0.8125rem] text-muted-foreground">No comparison yet</p>;
  }

  const { icon: Icon, tone, spoken } = DELTA_STYLES[delta.direction];
  const spokenText =
    delta.direction === 'flat'
      ? `${spoken} on ${delta.comparison}`
      : `${spoken} ${delta.text} on ${delta.comparison}`;

  return (
    <p className={cn('mt-1 text-[0.8125rem] font-semibold', tone)}>
      <span aria-hidden="true" className="inline-flex items-center gap-1">
        <Icon className="size-3.5" />
        {delta.text}
      </span>
      <span className="sr-only">{spokenText}</span>
    </p>
  );
}

function CellBody({ cell }: { cell: KpiCell }) {
  switch (cell.state) {
    case 'loading':
      return (
        <>
          <Skeleton className="mt-1 h-8 w-24" />
          <Skeleton className="mt-3 h-7 w-[7.5rem]" />
        </>
      );
    case 'empty':
      return (
        <>
          <p
            aria-hidden="true"
            className="font-display text-[1.75rem] font-semibold leading-[1.15] text-muted-foreground"
          >
            —
          </p>
          <p className="mt-1 text-[0.8125rem] text-muted-foreground">
            {cell.emptyText ?? 'No data yet'}
          </p>
          {cell.emptyAction ? (
            <Link href={cell.emptyAction.href} className={ACTION_CLASS}>
              {cell.emptyAction.label}
            </Link>
          ) : null}
        </>
      );
    case 'error':
      return (
        <>
          <p role="alert" className="mt-1 text-sm font-medium text-crit-foreground">
            Could not load
          </p>
          {cell.onRetry ? (
            <button
              type="button"
              onClick={cell.onRetry}
              aria-label={`Retry ${cell.label}`}
              className={ACTION_CLASS}
            >
              Retry
            </button>
          ) : null}
        </>
      );
    case 'ready':
      return (
        <>
          <p className="font-display text-[1.75rem] font-semibold tabular-nums leading-[1.15] text-foreground">
            {cell.value}
          </p>
          <Delta delta={cell.delta} />
          {cell.trend && cell.trend.length >= 2 ? (
            <Sparkline id={cell.id} points={cell.trend} />
          ) : null}
        </>
      );
  }
}

/**
 * One panel divided by hairlines: 2x2 below 760px, four columns from 760px up.
 * Every cell owns its state, so one failure never affects the others. Presentational:
 * the caller supplies already formatted strings.
 */
function KpiStrip({ cells, className }: KpiStripProps) {
  return (
    <ul
      aria-label="Key figures"
      className={cn(
        'grid grid-cols-2 overflow-hidden rounded-xl border border-border bg-card min-[760px]:grid-cols-4',
        className
      )}
    >
      {cells.map((cell) => (
        <li key={cell.id} className="-mb-px -me-px border-b border-e border-border">
          <div
            role="group"
            aria-label={cell.label}
            aria-busy={cell.state === 'loading' ? true : undefined}
            className="p-4"
          >
            <p className="text-[0.8125rem] text-muted-foreground">{cell.label}</p>
            <CellBody cell={cell} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export { KpiStrip };
