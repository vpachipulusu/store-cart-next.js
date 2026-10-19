import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getRange } from '@/components/ui/pagination';
import { OrderTable, type OrderRow } from '@/components/dashboard/orders/order-table';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import {
  fetchOrders,
  ORDERS_PAGE_SIZE,
  orderErrorMessage,
  type OrderListResponse,
} from '@/lib/api/orders';
import { logger } from '@/lib/logger';
import { formatMinor } from '@/lib/products/money';
import { isOrderStatus, ORDER_STATUS_LABELS, ORDER_STATUSES } from '@/lib/orders/schema';
import type { OrderStatus } from '@/lib/orders/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { isStoreInSetup } from '@/lib/stores/provisioning';
import { StoreSetupState } from '@/components/dashboard/store-setup-state';

export const metadata = { title: 'Orders' };

type Param = string | string[] | undefined;
type SearchParams = Promise<{ status?: Param; page?: Param }>;

const MAX_PAGE = 10_000;

function first(value: Param): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page, MAX_PAGE) : 1;
}

function pageHref(status: OrderStatus | undefined, page: number): string {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/dashboard/orders?${qs}` : '/dashboard/orders';
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

function toRows(list: OrderListResponse): OrderRow[] {
  return list.data.map((order) => ({
    id: order.id,
    status: order.status,
    total: formatMinor(order.total_minor, order.currency),
    itemCount: order.item_count,
    tracking: order.tracking_number ?? null,
    placed: formatDate(order.created_at),
  }));
}

export default async function OrdersPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const statusParam = first(params.status);
  const status = isOrderStatus(statusParam) ? statusParam : undefined;
  const page = parsePage(first(params.page));

  // The layout already explains a missing store or a failed store list, so there is nothing to list here.
  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;
  if (isStoreInSetup(selection.selected.status)) {
    const { id, name, status } = selection.selected;
    return <StoreSetupState storeId={id} storeName={name} status={status} />;
  }

  const result = await fetchOrders(selection.selected.id, {
    status,
    limit: ORDERS_PAGE_SIZE,
    offset: (page - 1) * ORDERS_PAGE_SIZE,
  });
  if (!result.success) {
    logger.error('Orders page: list failed', { status: result.status });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Orders</h1>
        <p className="text-muted-foreground">Orders for {selection.selected.name}</p>
      </div>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <form
            action="/dashboard/orders"
            method="get"
            role="search"
            className="flex flex-wrap items-end gap-3"
          >
            <div>
              <label htmlFor="order-status-filter" className="mb-1 block text-sm font-medium">
                Status
              </label>
              <select
                id="order-status-filter"
                name="status"
                defaultValue={status ?? ''}
                className="h-11 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <option value="">All statuses</option>
                {ORDER_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {ORDER_STATUS_LABELS[value]}
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit" variant="outline">
              Apply
            </Button>
            {status && (
              <Button variant="ghost" asChild>
                <Link href="/dashboard/orders">Clear filter</Link>
              </Button>
            )}
          </form>

          {!result.success ? (
            <ProductsLoadError
              message={orderErrorMessage(result)}
              retryHref={pageHref(status, page)}
            />
          ) : (
            <OrderList list={result.data} page={page} status={status} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function OrderList({
  list,
  page,
  status,
}: {
  list: OrderListResponse;
  page: number;
  status: OrderStatus | undefined;
}) {
  if (list.total === 0) {
    return (
      <div role="status" data-testid="no-orders" className="py-8 text-center text-sm">
        <p className="font-medium">{status ? 'No orders match this filter.' : 'No orders yet.'}</p>
        {!status && (
          <p className="text-muted-foreground">Orders appear here as customers place them.</p>
        )}
      </div>
    );
  }
  if (list.data.length === 0) {
    return (
      <p role="status" className="py-4 text-center text-sm text-muted-foreground">
        No orders on this page.{' '}
        <Link className="underline" href={pageHref(status, 1)}>
          Back to the first page
        </Link>
      </p>
    );
  }

  const range = getRange(page, ORDERS_PAGE_SIZE, list.total);
  return (
    <>
      <OrderTable rows={toRows(list)} />
      <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm tabular-nums text-muted-foreground">
          {`Showing ${range.from} to ${range.to} of ${list.total}`}
        </p>
        <div className="flex gap-2">
          {page > 1 && (
            <Button variant="outline" asChild>
              <Link href={pageHref(status, page - 1)}>Previous</Link>
            </Button>
          )}
          {page < range.pageCount && (
            <Button variant="outline" asChild>
              <Link href={pageHref(status, page + 1)}>Next</Link>
            </Button>
          )}
        </div>
      </nav>
    </>
  );
}
