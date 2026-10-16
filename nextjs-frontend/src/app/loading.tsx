import { Skeleton } from '@/components/ui/skeleton';

/** Route loading state: skeleton blocks shaped like a page (title, lead, cards), no spinner. */
export default function Loading() {
  return (
    <main
      role="status"
      aria-busy="true"
      aria-label="Loading"
      className="container min-h-screen space-y-8 py-12"
    >
      <div className="space-y-3">
        <Skeleton className="h-9 w-64 max-w-full" />
        <Skeleton className="h-5 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
      </div>
      <Skeleton className="h-64 w-full rounded-lg" />
    </main>
  );
}
