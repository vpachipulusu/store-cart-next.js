import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Search } from 'lucide-react';
import {
  ADMIN_STORES_PAGE_SIZE,
  ADMIN_STORE_STATUSES,
  adminErrorMessage,
  fetchAdminStores,
  type StoreStatus,
} from '@/lib/api/admin-stores';
import { logger } from '@/lib/logger';
import { isStalledProvisioning } from '@/lib/stores/provisioning';
import { StoreRowActions } from './store-row-actions';

type Param = string | string[] | undefined;
type SearchParams = Promise<{ q?: Param; status?: Param; org?: Param; page?: Param }>;

/** A repeated query param (?q=a&q=b) arrives as an array; only the first value counts. */
function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

const ORG_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

const STATUS_BADGE: Record<StoreStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  ACTIVE: 'default',
  PROVISIONING: 'secondary',
  FAILED: 'destructive',
  SUSPENDED: 'destructive',
  ARCHIVED: 'outline',
};

/** Deep pages are capped so a crafted ?page= never becomes an absurd offset. */
const MAX_PAGE = 10_000;

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page, MAX_PAGE) : 1;
}

function parseStatus(value: string | undefined): StoreStatus | undefined {
  return ADMIN_STORE_STATUSES.find((status) => status === value);
}

function pageHref(
  filters: { q?: string; status?: StoreStatus; org?: string },
  page: number
): string {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.status) params.set('status', filters.status);
  if (filters.org) params.set('org', filters.org);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/admin/stores?${qs}` : '/admin/stores';
}

export default async function AdminStoresPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const q = first(params.q)?.trim().slice(0, 100) || undefined;
  const status = parseStatus(first(params.status));
  const orgParam = first(params.org);
  const org = orgParam && ORG_ID_PATTERN.test(orgParam) ? orgParam : undefined;
  const page = parsePage(first(params.page));

  const result = await fetchAdminStores({
    search: q,
    status,
    organizationId: org,
    limit: ADMIN_STORES_PAGE_SIZE,
    offset: (page - 1) * ADMIN_STORES_PAGE_SIZE,
  });
  if (!result.success) {
    logger.error('Admin stores page: list failed', { status: result.status });
  }

  const stores = result.success ? result.data.stores : [];
  // Rendered per request on the server, so "now" is the request time (KAN-255 stuck re-run).
  const renderedAt = Date.now();
  const totalCount = result.success ? result.data.total_count : 0;
  const hasNext = page * ADMIN_STORES_PAGE_SIZE < totalCount;
  const filters = { q, status, org };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Stores</h1>
        <p className="text-muted-foreground">
          Every merchant store with its status and schema version
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form
            action="/admin/stores"
            method="get"
            className="flex items-center gap-4"
            role="search"
          >
            <div className="relative flex-1">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                placeholder="Search stores by name or slug..."
                aria-label="Search stores"
                className="pl-10"
                name="q"
                maxLength={100}
                defaultValue={q}
              />
            </div>
            <label className="sr-only" htmlFor="store-status-filter">
              Filter by status
            </label>
            <select
              id="store-status-filter"
              name="status"
              defaultValue={status ?? ''}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <option value="">All statuses</option>
              {ADMIN_STORE_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0) + value.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
            {org && <input type="hidden" name="org" value={org} />}
            <Button type="submit" variant="outline">
              Search
            </Button>
          </form>
          {org && (
            <p className="mt-4 text-sm text-muted-foreground">
              Showing the stores of {stores[0]?.organization_name ?? 'one organisation'}.{' '}
              <Link className="underline" href={pageHref({ q, status }, 1)}>
                Show all stores
              </Link>
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>All Stores ({totalCount})</CardTitle>
          <CardDescription>
            Suspend, unsuspend, re-run migrations or re-run provisioning for a store
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!result.success ? (
            <p role="alert" className="py-4 text-center text-sm text-destructive">
              {adminErrorMessage(result)}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Store</TableHead>
                    <TableHead>Organisation</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Schema version</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stores.map((store) => (
                    <TableRow key={store.id}>
                      <TableCell className="font-medium">
                        {store.name}
                        <span className="block text-xs font-normal text-muted-foreground">
                          {store.slug}
                        </span>
                      </TableCell>
                      <TableCell>{store.organization_name}</TableCell>
                      <TableCell>
                        <Badge variant={STATUS_BADGE[store.status]}>
                          {store.status.charAt(0) + store.status.slice(1).toLowerCase()}
                        </Badge>
                      </TableCell>
                      <TableCell>{store.schema_version}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {new Date(store.created_at).toLocaleDateString('en-GB', {
                          timeZone: 'UTC',
                        })}
                      </TableCell>
                      <TableCell className="text-right">
                        <StoreRowActions
                          storeId={store.id}
                          storeName={store.name}
                          status={store.status}
                          stalled={isStalledProvisioning(
                            store.status,
                            store.updated_at,
                            renderedAt
                          )}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {stores.length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">No stores found</p>
              )}
              {(page > 1 || hasNext) && (
                <nav aria-label="Pagination" className="flex justify-between pt-4">
                  {page > 1 ? (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(filters, page - 1)}>Previous</Link>
                    </Button>
                  ) : (
                    <span />
                  )}
                  {hasNext && (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(filters, page + 1)}>Next</Link>
                    </Button>
                  )}
                </nav>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
