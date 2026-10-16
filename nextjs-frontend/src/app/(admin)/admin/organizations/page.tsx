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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Search } from 'lucide-react';
import {
  ADMIN_STORES_PAGE_SIZE,
  adminErrorMessage,
  fetchAdminOrganizations,
} from '@/lib/api/admin-stores';
import { logger } from '@/lib/logger';

type Param = string | string[] | undefined;
type SearchParams = Promise<{ q?: Param; page?: Param }>;

/** A repeated query param (?q=a&q=b) arrives as an array; only the first value counts. */
function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Deep pages are capped so a crafted ?page= never becomes an absurd offset. */
const MAX_PAGE = 10_000;

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page, MAX_PAGE) : 1;
}

function pageHref(query: string | undefined, page: number): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/admin/organizations?${qs}` : '/admin/organizations';
}

export default async function AdminOrganizationsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const q = first(params.q)?.trim().slice(0, 100) || undefined;
  const page = parsePage(first(params.page));

  const result = await fetchAdminOrganizations({
    search: q,
    limit: ADMIN_STORES_PAGE_SIZE,
    offset: (page - 1) * ADMIN_STORES_PAGE_SIZE,
  });
  if (!result.success) {
    logger.error('Admin organisations page: list failed', { status: result.status });
  }

  const organizations = result.success ? result.data.organizations : [];
  const totalCount = result.success ? result.data.total_count : 0;
  const hasNext = page * ADMIN_STORES_PAGE_SIZE < totalCount;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Organisations</h1>
        <p className="text-muted-foreground">Merchant organisations and how many stores they own</p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form
            action="/admin/organizations"
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
                placeholder="Search organisations by name or slug..."
                aria-label="Search organisations"
                className="pl-10"
                name="q"
                maxLength={100}
                defaultValue={q}
              />
            </div>
            <Button type="submit" variant="outline">
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>All Organisations ({totalCount})</CardTitle>
          <CardDescription>Open an organisation&apos;s stores to manage them</CardDescription>
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
                    <TableHead>Organisation</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead>Stores</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {organizations.map((organization) => (
                    <TableRow key={organization.id}>
                      <TableCell className="font-medium">{organization.name}</TableCell>
                      <TableCell>{organization.slug}</TableCell>
                      <TableCell>{organization.store_count}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {new Date(organization.created_at).toLocaleDateString('en-GB', {
                          timeZone: 'UTC',
                        })}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" asChild>
                          <Link
                            href={`/admin/stores?org=${encodeURIComponent(organization.id)}`}
                            aria-label={`View stores of ${organization.name}`}
                          >
                            View stores
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {organizations.length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No organisations found
                </p>
              )}
              {(page > 1 || hasNext) && (
                <nav aria-label="Pagination" className="flex justify-between pt-4">
                  {page > 1 ? (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(q, page - 1)}>Previous</Link>
                    </Button>
                  ) : (
                    <span />
                  )}
                  {hasNext && (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(q, page + 1)}>Next</Link>
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
