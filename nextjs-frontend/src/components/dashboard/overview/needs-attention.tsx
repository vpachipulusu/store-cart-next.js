import Link from 'next/link';

import { StatusPill } from '@/components/ui/status-pill';
import { Panel } from './panel';
import { TEXT_ACTION_CLASS } from './styles';
import type { AttentionItem } from './types';

interface NeedsAttentionProps {
  items: ReadonlyArray<AttentionItem>;
}

export function NeedsAttention({ items }: NeedsAttentionProps) {
  return (
    <Panel title="Needs attention" titleId="needs-attention-title">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing needs attention</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2">
              <span className="flex items-center gap-2 text-sm text-foreground">
                <StatusPill variant="warn">{item.count}</StatusPill>
                {item.label}
              </span>
              <Link href={item.href} className={TEXT_ACTION_CLASS}>
                {item.actionLabel}
                <span className="sr-only"> {item.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
