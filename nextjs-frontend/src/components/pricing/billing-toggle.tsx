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
        className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
          billingPeriod === 'monthly'
            ? 'bg-theme-accent text-white'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        Monthly
      </button>
      <button
        type="button"
        onClick={() => onToggle('yearly')}
        className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
          billingPeriod === 'yearly'
            ? 'bg-theme-accent text-white'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        Yearly
        {yearlySavingsPercent !== undefined && yearlySavingsPercent > 0 && (
          <Badge variant="secondary" className="text-xs bg-theme-accent/15 text-theme-accent-dark border-theme-accent/30">
            Save {yearlySavingsPercent}%
          </Badge>
        )}
      </button>
    </div>
  );
}
