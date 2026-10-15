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
import { ADMIN_USERS_PAGE_SIZE, adminErrorMessage, fetchAdminUsers } from '@/lib/api/admin-users';
import { logger } from '@/lib/logger';
import { UserRowActions } from './user-row-actions';

type SearchParams = Promise<{ q?: string; page?: string }>;

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

function pageHref(query: string | undefined, page: number): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (page > 1) params.set('page', String(page));
  const qs = params.toString();
  return qs ? `/admin/users?${qs}` : '/admin/users';
}

export default async function AdminUsersPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const query = params.q?.trim() || undefined;
  const page = parsePage(params.page);

  const result = await fetchAdminUsers({
    search: query,
    limit: ADMIN_USERS_PAGE_SIZE,
    offset: (page - 1) * ADMIN_USERS_PAGE_SIZE,
  });
  if (!result.success) {
    logger.error('Admin users page: list failed', { status: result.status });
  }

  const users = result.success ? result.data.users : [];
  const totalCount = result.success ? result.data.total_count : 0;
  const hasNext = page * ADMIN_USERS_PAGE_SIZE < totalCount;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">User Management</h1>
        <p className="text-muted-foreground">View and manage all platform users</p>
      </div>

      {/* Search */}
      <Card>
        <CardContent className="pt-6">
          <form
            action="/admin/users"
            method="get"
            className="flex items-center gap-4"
            role="search"
          >
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                placeholder="Search users by email or name..."
                aria-label="Search users"
                className="pl-10"
                name="q"
                maxLength={100}
                defaultValue={query}
              />
            </div>
            <Button type="submit" variant="outline">
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle>All Users ({totalCount})</CardTitle>
          <CardDescription>Manage user accounts and admin access</CardDescription>
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
                    <TableHead>User</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Last login</TableHead>
                    <TableHead>Joined</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium">{user.display_name || '—'}</TableCell>
                      <TableCell>{user.email}</TableCell>
                      <TableCell>
                        {user.email_verified ? (
                          <Badge variant="default">Verified</Badge>
                        ) : (
                          <Badge variant="secondary">Unverified</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {user.is_admin ? (
                          <Badge variant="destructive" className="capitalize">
                            {(user.admin_role ?? 'admin').replace('_', ' ')}
                          </Badge>
                        ) : (
                          <span className="text-sm text-muted-foreground">User</span>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {user.last_login_at
                          ? new Date(user.last_login_at).toLocaleDateString()
                          : '—'}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {new Date(user.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <UserRowActions userId={user.id} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {users.length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">No users found</p>
              )}
              {(page > 1 || hasNext) && (
                <nav aria-label="Pagination" className="flex justify-between pt-4">
                  {page > 1 ? (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(query, page - 1)}>Previous</Link>
                    </Button>
                  ) : (
                    <span />
                  )}
                  {hasNext && (
                    <Button variant="outline" asChild>
                      <Link href={pageHref(query, page + 1)}>Next</Link>
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
