import type { ReactNode } from 'react';
import { Mail } from 'lucide-react';
import { cn } from '@/lib/utils';

/** Inline text link with a 44px target (plan 9: auth links are real targets). */
export const AUTH_LINK_CLASS =
  'inline-flex min-h-11 items-center font-medium text-accent-ink underline-offset-4 hover:underline';

/** The one h1 on every auth page. Card titles render h3, so the pages use this instead. */
export function AuthHeading({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h1
      className={cn('font-display text-2xl font-semibold leading-tight tracking-tight', className)}
    >
      {children}
    </h1>
  );
}

/** Icon tile for the single-purpose pages (reset password, verify email). */
export function AuthIconTile({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-accent-ink">
      {children}
    </div>
  );
}

export { Mail as AuthMailIcon };

/** "Or continue with email" rule between OAuth buttons and the form. */
export function AuthDivider({ children }: { children: ReactNode }) {
  return (
    <div className="relative">
      <div className="absolute inset-0 flex items-center" aria-hidden="true">
        <div className="w-full border-t border-border" />
      </div>
      <div className="relative flex justify-center text-xs uppercase">
        <span className="bg-background px-2 text-muted-foreground">{children}</span>
      </div>
    </div>
  );
}
