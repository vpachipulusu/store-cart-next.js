import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PageLinks } from '@/components/storefront/page-links';
import { ProductGrid } from '@/components/storefront/product-grid';
import { searchProducts } from '@/lib/api/storefront-catalogue';
import { cleanSearch, MAX_SEARCH_LENGTH, parsePage } from '@/lib/storefront/catalogue';
import { searchMetadata } from '@/lib/storefront/seo';
import { originFor } from '@/lib/storefront/store-origin';

/**
 * Search and "all products" (KAN-75): `/search?q=...&page=n`. Dynamic and uncached (every query is a new key);
 * the backend matches titles only. Never indexed; the pages it links to are.
 */

type Params = Promise<{ slug: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}): Promise<Metadata> {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  return searchMetadata(originFor(slug), cleanSearch(query.q));
}

function searchHref(query: string, page: number): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (page > 1) params.set('page', String(page));
  const search = params.toString();
  return search ? `/search?${search}` : '/search';
}

export default async function SearchPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const [{ slug }, raw] = await Promise.all([params, searchParams]);
  const query = cleanSearch(raw.q);
  const page = parsePage(raw.page);
  const results = await searchProducts(slug, query, page);
  if (!results) notFound();

  const heading = query ? `Results for “${query}”` : 'All products';
  const count = `${results.total} ${results.total === 1 ? 'product' : 'products'}`;

  return (
    <>
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">{heading}</h1>
      <form role="search" action="/search" method="get" className="mt-6 flex max-w-xl gap-2">
        <label htmlFor="search-page-q" className="sr-only">
          Search products
        </label>
        <input
          id="search-page-q"
          name="q"
          type="search"
          defaultValue={query}
          maxLength={MAX_SEARCH_LENGTH}
          placeholder="Search products"
          className="h-11 flex-1 rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          type="submit"
          className="h-11 rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          Search
        </button>
      </form>
      <p role="status" className="mt-4 text-sm text-muted-foreground">
        {count}
      </p>
      <div className="mt-8">
        <ProductGrid
          products={results.items}
          currency={results.currency}
          emptyMessage={query ? 'No products match your search.' : 'No products yet.'}
        />
      </div>
      <PageLinks
        page={results.page}
        pageCount={results.pageCount}
        hrefFor={(target) => searchHref(query, target)}
      />
    </>
  );
}
