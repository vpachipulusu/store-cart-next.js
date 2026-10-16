import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

interface FormPageSkeletonProps {
  label: string;
  panels: number;
}

/** Loading state for a form page: same panel rhythm as the loaded page, announced once to assistive tech. */
export function FormPageSkeleton({ label, panels }: FormPageSkeletonProps) {
  return (
    <div role="status" aria-label={label} aria-busy="true" className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-5 w-64 max-w-full" />
      </div>
      {Array.from({ length: panels }, (_, index) => (
        <Skeleton key={index} className="h-48 w-full rounded-xl" />
      ))}
    </div>
  );
}

interface PageHeaderProps {
  title: string;
  description: string;
}

/** The page's only h1. */
export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <header>
      <h1 className="text-3xl tracking-tight">{title}</h1>
      <p className="text-muted-foreground">{description}</p>
    </header>
  );
}

interface PanelHintProps {
  children: ReactNode;
  className?: string;
}

/** One-line explainer under a panel heading. */
export function PanelHint({ children, className }: PanelHintProps) {
  return <p className={cn('mb-4 text-sm text-muted-foreground', className)}>{children}</p>;
}

interface FormActionsProps {
  isSaving: boolean;
  saveLabel: string;
  secondaryLabel: string;
  onSecondary: () => void;
}

/** Save and secondary buttons. They stack full width on phones; saving swaps the label and locks both. */
export function FormActions({
  isSaving,
  saveLabel,
  secondaryLabel,
  onSecondary,
}: FormActionsProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <Button type="submit" variant="accent" disabled={isSaving} className="w-full sm:w-auto">
        {isSaving && <Loader2 aria-hidden="true" className="motion-safe:animate-spin" />}
        {isSaving ? 'Saving…' : saveLabel}
      </Button>
      <Button
        type="button"
        variant="outline"
        disabled={isSaving}
        onClick={onSecondary}
        className="w-full sm:w-auto"
      >
        {secondaryLabel}
      </Button>
    </div>
  );
}
