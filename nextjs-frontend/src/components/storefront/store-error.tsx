'use client';

import { useEffect, useRef } from 'react';
import * as Sentry from '@sentry/nextjs';
import { Button } from '@/components/ui/button';

/**
 * A store page could not load (backend outage or rate limit, never a missing store). Reports to Sentry, moves
 * focus to the heading, and offers a retry. Never cached: thrown reads are not stored.
 */
export function StoreError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section role="alert" className="container mx-auto max-w-md py-16 text-center">
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl font-semibold outline-none"
      >
        This page is temporarily unavailable
      </h1>
      <p className="mt-2 text-muted-foreground">Please try again in a moment.</p>
      {error.digest ? (
        <p className="mt-2 text-sm text-muted-foreground">Error ID: {error.digest}</p>
      ) : null}
      <Button type="button" size="lg" className="mt-6" onClick={reset}>
        Try again
      </Button>
    </section>
  );
}
