import Link from 'next/link';
import { Search } from 'lucide-react';
import { CartCount } from './cart-count';
import { MAX_SEARCH_LENGTH, type StoreCategory } from '@/lib/storefront/catalogue';

interface StoreHeaderProps {
  storeName: string;
  categories: readonly StoreCategory[];
}

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Store name, search and basket, then the top-level categories as a scrollable nav row. */
export function StoreHeader({ storeName, categories }: StoreHeaderProps) {
  return (
    <header className="border-b bg-background">
      <div className="container flex flex-wrap items-center gap-3 py-3 sm:flex-nowrap">
        <Link
          href="/"
          className={`mr-auto rounded-md font-display text-xl font-semibold tracking-tight sm:text-2xl ${FOCUS}`}
        >
          {storeName}
        </Link>
        <form
          role="search"
          action="/search"
          method="get"
          className="order-last flex w-full items-center gap-2 sm:order-none sm:w-auto"
        >
          <label htmlFor="store-search" className="sr-only">
            Search products
          </label>
          <input
            id="store-search"
            name="q"
            type="search"
            maxLength={MAX_SEARCH_LENGTH}
            placeholder="Search products"
            className={`h-11 w-full rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground sm:w-64 ${FOCUS}`}
          />
          <button
            type="submit"
            aria-label="Search"
            className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-input hover:bg-accent hover:text-accent-foreground ${FOCUS}`}
          >
            <Search className="h-4 w-4" aria-hidden="true" />
          </button>
        </form>
        <CartCount />
      </div>
      {categories.length > 0 ? (
        <nav aria-label="Categories" className="border-t">
          <ul className="container flex gap-1 overflow-x-auto py-1">
            {categories.map((category) => (
              <li key={category.slug} className="shrink-0">
                <Link
                  href={`/categories/${category.slug}`}
                  className={`inline-flex h-11 items-center rounded-md px-3 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground ${FOCUS}`}
                >
                  {category.name}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </header>
  );
}
