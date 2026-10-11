'use client';

import * as React from 'react';
import { useEffect } from 'react';
import * as Sentry from '@sentry/nextjs';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import Link from 'next/link';

/**
 * Error Boundary Component
 *
 * Global error boundary for the application
 * Catches and displays errors with recovery options
 * Uses React 19 error boundary patterns
 *
 * @param error - The error object
 * @param reset - Function to reset the error boundary
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <div className="container flex min-h-screen items-center justify-center py-10">
      <Card className="w-full max-w-md border-destructive/50">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="h-8 w-8 text-destructive" />
          </div>
          <CardTitle className="text-2xl font-semibold">Something went wrong!</CardTitle>
          <CardDescription>
            We encountered an unexpected error. Don't worry, we're on it!
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {process.env.NODE_ENV === 'development' && (
            <div className="rounded-lg bg-muted p-4">
              <p className="mb-2 text-sm font-semibold">Error Details:</p>
              <pre className="scrollbar-thin max-h-40 overflow-auto text-xs">{error.message}</pre>
              {error.digest && (
                <p className="mt-2 text-xs text-muted-foreground">Error ID: {error.digest}</p>
              )}
            </div>
          )}
          <div className="text-center text-sm text-muted-foreground">
            <p>If this problem persists, please contact support with the error ID above.</p>
          </div>
        </CardContent>
        <CardFooter className="flex flex-col gap-2 sm:flex-row">
          <Button onClick={reset} className="w-full sm:w-auto" size="lg">
            <RefreshCw className="mr-2 h-4 w-4" />
            Try Again
          </Button>
          <Button variant="outline" asChild className="w-full sm:w-auto" size="lg">
            <Link href="/">
              <Home className="mr-2 h-4 w-4" />
              Go Home
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
