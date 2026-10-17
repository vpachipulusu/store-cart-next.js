import Link from 'next/link';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getRange } from '@/components/ui/pagination';
import { ProductTable, type ProductRow } from '@/components/dashboard/products/product-table';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import {
  fetchProducts,
  PRODUCTS_PAGE_SIZE,
  productErrorMessage,
  type ProductListResponse,
} from '@/lib/api/products';
import { logger } from '@/lib/logger';
import { formatPriceRange } from '@/lib/products/money';
import { isEntityId, PRODUCT_STATUSES, type ProductStatus } from '@/lib/products/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';

export const metadata = { title: 'Products' };

type Param = string | string[] | undefined;
type SearchParams = Promise<{ status?: Param; category?: Param; page?: Param }>;

const MAX_PAGE = 10_000;

function first(value: Param): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page, MAX_PAGE) : 1;
}

type Filters = { status?: ProductStatus; category?: string };

function pageHref(filters: Filters, page: number): string {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.category) params.set('category', filters.category);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/dashboard/products?${qs}` : '/dashboard/products';
}

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});

/** A malformed date shows a dash instead of breaking the whole list. */
function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : DATE_FORMAT.format(date);
}

function toRows(list: ProductListResponse): ProductRow[] {
  return list.data.map((product) => ({
    id: product.id,
    title: product.title,
    slug: product.slug,
    status: product.status,
    variantCount: product.variant_count,
    price: formatPriceRange(product.min_price_minor, product.max_price_minor, list.currency),
    updated: formatDate(product.updated_at),
  }));
}

export default async function ProductsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const statusParam = first(params.status);
  const status = PRODUCT_STATUSES.find((value) => value === statusParam);
  const categoryParam = first(params.category);
  const category = isEntityId(categoryParam) ? categoryParam : undefined;
  const page = parsePage(first(params.page));
  const filters: Filters = { status, category };

  // The layout already explains a missing store or a failed store list, so there is nothing to list here.
  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;

  const result = await fetchProducts(selection.selected.id, {
    status,
    categoryId: category,
    limit: PRODUCTS_PAGE_SIZE,
    offset: (page - 1) * PRODUCTS_PAGE_SIZE,
  });
  if (!result.success) {
    logger.error('Products page: list failed', { status: result.status });
  }

  const hasFilters = Boolean(status || category);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Products</h1>
          <p className="text-muted-foreground">
            Products for {selection.selected.name}, with their variants and prices
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/products/new">
            <Plus aria-hidden="true" />
            New product
          </Link>
        </Button>
      </div>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <form
            action="/dashboard/products"
            method="get"
            role="search"
            className="flex flex-wrap items-end gap-3"
          >
            <div>
              <label htmlFor="product-status-filter" className="mb-1 block text-sm font-medium">
                Status
              </label>
              <select
                id="product-status-filter"
                name="status"
                defaultValue={status ?? ''}
                className="h-11 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <option value="">All statuses</option>
                <option value="active">Active</option>
                <option value="draft">Draft</option>
              </select>
            </div>
            {category && <input type="hidden" name="category" value={category} />}
            <Button type="submit" variant="outline">
              Apply
            </Button>
            {hasFilters && (
              <Button variant="ghost" asChild>
                <Link href="/dashboard/products">Clear filters</Link>
              </Button>
            )}
          </form>
          {category && (
            <p className="text-sm text-muted-foreground" data-testid="category-filter">
              Showing one category (<code>{category}</code>).
            </p>
          )}

          {!result.success ? (
            <ProductsLoadError
              message={productErrorMessage(result)}
              retryHref={pageHref(filters, page)}
            />
          ) : (
            <ProductList list={result.data} page={page} filters={filters} hasFilters={hasFilters} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ProductList({
  list,
  page,
  filters,
  hasFilters,
}: {
  list: ProductListResponse;
  page: number;
  filters: Filters;
  hasFilters: boolean;
}) {
  if (list.total === 0) {
    return (
      <div role="status" data-testid="no-products" className="py-8 text-center text-sm">
        <p className="font-medium">
          {hasFilters ? 'No products match these filters.' : 'No products yet.'}
        </p>
        {!hasFilters && (
          <p className="text-muted-foreground">Add your first product to start selling.</p>
        )}
      </div>
    );
  }
  if (list.data.length === 0) {
    return (
      <p role="status" className="py-4 text-center text-sm text-muted-foreground">
        No products on this page.{' '}
        <Link className="underline" href={pageHref(filters, 1)}>
          Back to the first page
        </Link>
      </p>
    );
  }

  const range = getRange(page, PRODUCTS_PAGE_SIZE, list.total);
  return (
    <>
      <ProductTable rows={toRows(list)} />
      <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm tabular-nums text-muted-foreground">
          {`Showing ${range.from} to ${range.to} of ${list.total}`}
        </p>
        <div className="flex gap-2">
          {page > 1 && (
            <Button variant="outline" asChild>
              <Link href={pageHref(filters, page - 1)}>Previous</Link>
            </Button>
          )}
          {page < range.pageCount && (
            <Button variant="outline" asChild>
              <Link href={pageHref(filters, page + 1)}>Next</Link>
            </Button>
          )}
        </div>
      </nav>
    </>
  );
}
