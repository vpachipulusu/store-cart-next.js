import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { SearchX } from 'lucide-react';

/** Custom 404. One calm panel, one way out. */
export default function NotFound() {
  return (
    <main className="container flex min-h-screen items-center justify-center py-10">
      <section className="w-full max-w-md rounded-lg border bg-card p-8 text-center text-card-foreground">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
          <SearchX className="h-7 w-7 text-accent-ink" aria-hidden="true" />
        </div>
        <p className="font-display text-6xl text-accent-ink" aria-hidden="true">
          404
        </p>
        <h1 className="mt-2 font-display text-2xl">Page not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you are looking for does not exist or has moved.
        </p>
        <Button asChild size="lg" variant="accent" className="mt-6">
          <Link href="/">Go home</Link>
        </Button>
      </section>
    </main>
  );
}
