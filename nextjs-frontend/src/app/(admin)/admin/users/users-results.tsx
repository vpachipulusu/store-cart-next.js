import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ADMIN_USERS_PAGE_SIZE, adminErrorMessage, fetchAdminUsers } from '@/lib/api/admin-users';
import { logger } from '@/lib/logger';
import { EmptyCell } from '../_components/empty-cell';
import { UserRowActions } from './user-row-actions';

type UsersResultsProps = {
  query: string | undefined;
  page: number;
};

export const USERS_CLEAR_HREF = '/admin/users';

export function usersPageHref(query: string | undefined, page: number): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `${USERS_CLEAR_HREF}?${qs}` : USERS_CLEAR_HREF;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function emptyMessage(query: string | undefined, page: number): string {
  if (page > 1) return 'No users on this page';
  return query ? `No users match '${query}'` : 'No users yet';
}

export async function UsersResults({ query, page }: UsersResultsProps) {
  const result = await fetchAdminUsers({
    search: query,
    limit: ADMIN_USERS_PAGE_SIZE,
    offset: (page - 1) * ADMIN_USERS_PAGE_SIZE,
  });

  if (!result.success) {
    logger.error('Admin users page: list failed', { status: result.status });
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/50 p-4 text-sm text-destructive"
      >
        <p className="flex items-center gap-2">
          <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
          {adminErrorMessage(result)}
        </p>
        <Button variant="outline" asChild>
          <Link href={usersPageHref(query, page)}>Retry</Link>
        </Button>
      </div>
    );
  }

  const { users, total_count: totalCount } = result.data;
  const hasNext = page * ADMIN_USERS_PAGE_SIZE < totalCount;

  return (
    <section aria-labelledby="users-heading">
      <h2 id="users-heading" className="mb-3 text-lg font-semibold">
        All Users ({totalCount})
      </h2>
      {users.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <p className="break-all font-medium">{emptyMessage(query, page)}</p>
          {(query || page > 1) && (
            <Button variant="outline" asChild>
              <Link href={query && page === 1 ? USERS_CLEAR_HREF : usersPageHref(query, 1)}>
                {query && page === 1 ? 'Clear' : 'Back to first page'}
              </Link>
            </Button>
          )}
        </div>
      ) : (
        <Table stacked>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Last sign-in</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((user) => (
              <TableRow key={user.id}>
                <TableCell className="max-sm:w-full">
                  <div className="font-medium">
                    {user.display_name || <span className="text-muted-foreground">Not set</span>}
                  </div>
                  <div className="break-all text-muted-foreground">{user.email}</div>
                </TableCell>
                <TableCell label="Status">
                  {user.email_verified ? (
                    <StatusPill variant="good">Verified</StatusPill>
                  ) : (
                    <StatusPill variant="warn">Unverified</StatusPill>
                  )}
                </TableCell>
                <TableCell label="Role">
                  {user.is_admin ? (
                    <StatusPill variant="info" className="capitalize">
                      {(user.admin_role ?? 'admin').replace('_', ' ')}
                    </StatusPill>
                  ) : (
                    <span className="text-muted-foreground">User</span>
                  )}
                </TableCell>
                <TableCell label="Last sign-in" className="text-muted-foreground">
                  {user.last_login_at ? formatDate(user.last_login_at) : 'Never'}
                </TableCell>
                <TableCell label="Joined" className="text-muted-foreground">
                  {user.created_at ? formatDate(user.created_at) : <EmptyCell />}
                </TableCell>
                <TableCell className="text-right">
                  <UserRowActions userId={user.id} userLabel={user.display_name || user.email} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {(page > 1 || hasNext) && (
        <nav aria-label="Pagination" className="flex justify-between pt-4">
          {page > 1 ? (
            <Button variant="outline" asChild>
              <Link href={usersPageHref(query, page - 1)}>Previous</Link>
            </Button>
          ) : (
            <span />
          )}
          {hasNext && (
            <Button variant="outline" asChild>
              <Link href={usersPageHref(query, page + 1)}>Next</Link>
            </Button>
          )}
        </nav>
      )}
    </section>
  );
}
