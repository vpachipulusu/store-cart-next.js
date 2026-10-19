'use client';

import { Button } from '@/components/ui/button';

/** The store could not be loaded (backend outage or rate limit). Never cached; the shopper can retry. */
export default function StoreError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section role="alert" className="mx-auto max-w-md py-16 text-center">
      <h1 className="font-display text-2xl font-semibold">This page is temporarily unavailable</h1>
      <p className="mt-2 text-muted-foreground">Please try again in a moment.</p>
      <Button type="button" size="lg" className="mt-6" onClick={reset}>
        Try again
      </Button>
    </section>
  );
}
