'use client';

import { useRef } from 'react';
import type { KeyboardEvent } from 'react';

type BillingPeriod = 'monthly' | 'yearly';

interface BillingToggleProps {
  billingPeriod: BillingPeriod;
  onToggle: (period: BillingPeriod) => void;
  yearlySavingsPercent?: number;
}

const PERIODS: { value: BillingPeriod; label: string }[] = [
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
];

const PREVIOUS_KEYS = ['ArrowLeft', 'ArrowUp'];
const NEXT_KEYS = ['ArrowRight', 'ArrowDown'];

/** Index of the option a key moves to, or null when the key is not a navigation key. */
function targetIndex(key: string, current: number): number | null {
  if (key === 'Home') return 0;
  if (key === 'End') return PERIODS.length - 1;
  if (PREVIOUS_KEYS.includes(key)) return (current - 1 + PERIODS.length) % PERIODS.length;
  if (NEXT_KEYS.includes(key)) return (current + 1) % PERIODS.length;
  return null;
}

export function BillingToggle({
  billingPeriod,
  onToggle,
  yearlySavingsPercent,
}: BillingToggleProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const showSavings =
    yearlySavingsPercent !== undefined && Number.isFinite(yearlySavingsPercent)
      ? yearlySavingsPercent > 0
      : false;

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = targetIndex(event.key, index);
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
    onToggle(PERIODS[next].value);
  };

  return (
    <div
      role="radiogroup"
      aria-label="Billing period"
      className="flex items-center justify-center gap-2"
    >
      {PERIODS.map(({ value, label }, index) => {
        const selected = billingPeriod === value;
        return (
          <button
            key={value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onToggle(value)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`flex min-h-11 min-w-24 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors motion-reduce:transition-none ${
              selected
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {label}
            {value === 'yearly' && showSavings && (
              <span className="text-xs">Save {yearlySavingsPercent}%</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
