import Link from 'next/link';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PageLinksProps {
  page: number;
  pageCount: number;
  /** The URL of a page number (page 1 should be the bare listing URL). */
  hrefFor: (page: number) => string;
}

const LINK =
  'inline-flex h-11 items-center gap-1 rounded-md border border-input px-4 text-sm font-medium hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Server-rendered previous and next links, so listings stay cacheable and crawlable. */
export function PageLinks({ page, pageCount, hrefFor }: PageLinksProps) {
  if (pageCount <= 1) return null;
  return (
    <nav aria-label="Pagination" className="mt-10 flex items-center justify-between gap-3">
      {page > 1 ? (
        <Link href={hrefFor(page - 1)} rel="prev" className={LINK}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          Previous
        </Link>
      ) : (
        <span />
      )}
      <p className="text-sm tabular-nums text-muted-foreground">
        Page {page} of {pageCount}
      </p>
      {page < pageCount ? (
        <Link href={hrefFor(page + 1)} rel="next" className={LINK}>
          Next
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
