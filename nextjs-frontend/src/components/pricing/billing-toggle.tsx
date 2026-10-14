'use client';

import { Badge } from '@/components/ui/badge';

interface BillingToggleProps {
  billingPeriod: 'monthly' | 'yearly';
  onToggle: (period: 'monthly' | 'yearly') => void;
  yearlySavingsPercent?: number;
}

export function BillingToggle({
  billingPeriod,
  onToggle,
  yearlySavingsPercent,
}: BillingToggleProps) {
  return (
    <div className="flex items-center justify-center gap-4">
      <button
        type="button"
        onClick={() => onToggle('monthly')}
        className={`min-h-11 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
          billingPeriod === 'monthly'
            ? 'bg-cta text-cta-foreground'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        Monthly
      </button>
      <button
        type="button"
        onClick={() => onToggle('yearly')}
        className={`flex min-h-11 items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
          billingPeriod === 'yearly'
            ? 'bg-cta text-cta-foreground'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        Yearly
        {yearlySavingsPercent !== undefined && yearlySavingsPercent > 0 && (
          <Badge
            variant="secondary"
            className="border-theme-accent/30 bg-theme-accent/15 text-xs text-theme-accent-dark"
          >
            Save {yearlySavingsPercent}%
          </Badge>
        )}
      </button>
    </div>
  );
}
