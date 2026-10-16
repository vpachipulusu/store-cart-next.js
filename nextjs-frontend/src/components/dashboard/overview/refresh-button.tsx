'use client';

import { useRouter } from 'next/navigation';

import { cn } from '@/lib/utils';
import { TEXT_ACTION_CLASS } from './styles';

interface RefreshButtonProps {
  label: string;
  ariaLabel: string;
  className?: string;
}

/** Re-runs the server render of the page; the only client code a failed panel needs. */
export function RefreshButton({ label, ariaLabel, className }: RefreshButtonProps) {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => router.refresh()}
      aria-label={ariaLabel}
      className={cn(TEXT_ACTION_CLASS, className)}
    >
      {label}
    </button>
  );
}
