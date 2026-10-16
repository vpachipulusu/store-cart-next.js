import Link from 'next/link';

import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusPill } from '@/components/ui/status-pill';
import { cn } from '@/lib/utils';

export interface UsageMeterItem {
  id: string;
  label: string;
  used: number;
  /** null means the plan has no cap for this resource. */
  limit: number | null;
}

export interface CompareAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

export interface PlanUsageMeterProps {
  items: UsageMeterItem[];
  state?: 'ready' | 'loading' | 'error';
  onRetry?: () => void;
  compareAction?: CompareAction;
  className?: string;
}

/** Share of the limit at which the warn pill appears. */
const NEAR_LIMIT_RATIO = 0.8;

type UsageLevel = 'ok' | 'near' | 'full';

function usageLevel(used: number, limit: number): UsageLevel {
  if (limit <= 0 || used >= limit) return 'full';
  return used / limit >= NEAR_LIMIT_RATIO ? 'near' : 'ok';
}

const LEVEL_SUFFIX: Record<UsageLevel, string> = {
  ok: '',
  near: ', near limit',
  full: ', limit reached',
};

const FILL_CLASS: Record<UsageLevel, string> = {
  ok: 'bg-cta',
  near: 'bg-warn-foreground',
  full: 'bg-crit-foreground',
};

const ACTION_CLASS = cn(buttonVariants({ variant: 'outline' }), 'min-h-11 w-full');

function UsageRow({ item }: { item: UsageMeterItem }) {
  const { label, used, limit } = item;

  if (limit === null) {
    return (
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-[0.8125rem] tabular-nums text-muted-foreground">
          {used} used, unlimited
        </p>
      </div>
    );
  }

  const level = usageLevel(used, limit);
  const value = Math.min(used, Math.max(limit, 0));
  const percent = limit > 0 ? Math.min(100, (used / limit) * 100) : 100;

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-[0.8125rem] tabular-nums text-muted-foreground">
          {used} of {limit}
        </p>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={value}
        aria-valuetext={`${used} of ${limit} used${LEVEL_SUFFIX[level]}`}
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-secondary"
      >
        <div
          className={cn('h-full rounded-full motion-safe:transition-[width]', FILL_CLASS[level])}
          style={{ width: `${percent}%` }}
        />
      </div>
      {level === 'near' ? (
        <StatusPill variant="warn" className="mt-1.5">
          Near limit
        </StatusPill>
      ) : null}
      {level === 'full' ? (
        <StatusPill variant="crit" className="mt-1.5">
          Limit reached
        </StatusPill>
      ) : null}
    </div>
  );
}

function CompareButton({ action }: { action: CompareAction }) {
  if (action.href) {
    return (
      <Link href={action.href} className={ACTION_CLASS}>
        {action.label}
      </Link>
    );
  }

  return (
    <button type="button" onClick={action.onClick} className={ACTION_CLASS}>
      {action.label}
    </button>
  );
}

function MeterBody({
  items,
  state,
  onRetry,
}: Pick<PlanUsageMeterProps, 'items' | 'state' | 'onRetry'>) {
  if (state === 'loading') {
    return (
      <>
        {[0, 1, 2].map((index) => (
          <div key={index} className="space-y-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-2 w-full rounded-full" />
          </div>
        ))}
      </>
    );
  }

  if (state === 'error') {
    return (
      <div>
        <p role="alert" className="text-sm font-medium text-crit-foreground">
          Could not load plan usage
        </p>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            aria-label="Retry plan usage"
            className="inline-flex min-h-11 items-center rounded-md px-1 text-sm font-semibold text-accent-ink underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Retry
          </button>
        ) : null}
      </div>
    );
  }

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No plan limits to show</p>;
  }

  return (
    <>
      {items.map((item) => (
        <UsageRow key={item.id} item={item} />
      ))}
    </>
  );
}

/**
 * Plan usage panel. Meter semantics (role=meter with a spoken value) plus a pill carry
 * the state, so colour is never the only signal. Presentational: callers pass counts.
 */
function PlanUsageMeter({
  items,
  state = 'ready',
  onRetry,
  compareAction,
  className,
}: PlanUsageMeterProps) {
  return (
    <div
      role="group"
      aria-label="Plan usage"
      aria-busy={state === 'loading' ? true : undefined}
      className={cn('space-y-4 rounded-xl border border-border bg-card p-4', className)}
    >
      <MeterBody items={items} state={state} onRetry={onRetry} />
      {compareAction && state === 'ready' ? <CompareButton action={compareAction} /> : null}
    </div>
  );
}

export { PlanUsageMeter };
