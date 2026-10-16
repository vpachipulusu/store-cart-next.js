import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface PanelProps {
  title: string;
  titleId: string;
  busy?: boolean;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** A single bordered surface with an h2. Panels never nest, so there is no card inside a card. */
export function Panel({ title, titleId, busy, action, children, className }: PanelProps) {
  return (
    <section
      aria-labelledby={titleId}
      aria-busy={busy ? true : undefined}
      className={cn('rounded-xl border border-border bg-card p-4', className)}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id={titleId} className="font-display text-lg font-semibold text-foreground">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}
