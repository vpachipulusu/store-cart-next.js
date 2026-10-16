'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { AlertCircle } from 'lucide-react';
import type { AuthFormError } from './auth-form-errors';

/** Marks an invalid control with a 2px border; the error line carries the text (plan 5.8). */
export const FIELD_ERROR_CLASS =
  'aria-[invalid=true]:border-2 aria-[invalid=true]:border-crit-foreground';

interface AuthFormAlertProps {
  error: AuthFormError;
}

/**
 * Form-level alert panel (plan 5.8): icon, bold summary and a plain sentence. It takes focus when
 * it appears, which is how a failed submit with no field errors is announced and reached.
 */
export function AuthFormAlert({ error }: AuthFormAlertProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="flex gap-3 rounded-lg border-2 border-crit-foreground bg-crit p-3 text-sm text-crit-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-semibold">{error.title}</p>
        <p>{error.message}</p>
        {error.kind === 'suspended' && (
          <Link href="/contact" className="inline-flex min-h-11 items-center font-medium underline">
            Contact support
          </Link>
        )}
      </div>
    </div>
  );
}
