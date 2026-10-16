'use client';

import '@/app/globals.css';
import * as Sentry from '@sentry/nextjs';
import { useEffect, useRef } from 'react';

/**
 * Last-resort boundary: replaces the root layout, so it brings its own html shell and
 * the global stylesheet (the default light tokens). Plain elements only; the router
 * or providers may be what failed, so the home link is an anchor.
 */
export default function GlobalError({
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

  const buttonBase =
    'inline-flex h-12 items-center justify-center rounded-md px-8 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring';

  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <main className="flex min-h-screen items-center justify-center px-4 py-10">
          <section className="w-full max-w-md rounded-lg border-2 border-crit-foreground bg-crit p-8 text-center text-crit-foreground">
            <h1 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold outline-none">
              Something went wrong
            </h1>
            <p className="mt-2 text-sm">
              The page could not be shown. Try again, or go back to the home page.
            </p>
            {error.digest && <p className="mt-2 text-sm">Error ID: {error.digest}</p>}
            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
              <button
                type="button"
                onClick={reset}
                className={`${buttonBase} bg-cta text-cta-foreground hover:bg-cta-hover`}
              >
                Try again
              </button>
              {/* Plain anchor on purpose: a full page load recovers even if the router failed. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a
                href="/"
                className={`${buttonBase} border border-input bg-background text-foreground`}
              >
                Go home
              </a>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
