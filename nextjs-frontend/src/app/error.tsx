'use client';

import { useEffect, useRef } from 'react';
import * as Sentry from '@sentry/nextjs';
import Link from 'next/link';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * Route error boundary. Reports to Sentry; the message is never shown to users,
 * only the digest so support can find the log entry.
 */
export default function Error({
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

  // Move focus to the heading so keyboard and screen-reader users start here.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <div className="container flex min-h-[60vh] items-center justify-center py-10">
      <section className="w-full max-w-md rounded-lg border-2 border-crit-foreground bg-crit p-8 text-center text-crit-foreground">
        <AlertTriangle className="mx-auto mb-4 h-8 w-8" aria-hidden="true" />
        <h1 ref={headingRef} tabIndex={-1} className="font-display text-2xl outline-none">
          Something went wrong
        </h1>
        <p className="mt-2 text-sm">
          We hit an unexpected problem. Try again, or go back to the home page.
        </p>
        {error.digest && <p className="mt-2 text-sm">Error ID: {error.digest}</p>}
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <Button onClick={reset} size="lg" variant="accent">
            Try again
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/">Go home</Link>
          </Button>
        </div>
      </section>
    </div>
  );
}
