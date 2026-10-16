import { Suspense } from 'react';
import { Search } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TableSkeleton } from '../_components/table-skeleton';
import { UsersResults } from './users-results';

type SearchParams = Promise<{ q?: string; page?: string }>;

const MAX_QUERY_LENGTH = 100;
const USERS_COLUMNS = ['User', 'Status', 'Role', 'Last sign-in', 'Joined', 'Actions'];

function parsePage(value: string | undefined): number {
  const page = Number.parseInt(value ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

export default async function AdminUsersPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const query = params.q?.trim().slice(0, MAX_QUERY_LENGTH) || undefined;
  const page = parsePage(params.page);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">User Management</h1>
        <p className="text-muted-foreground">View and manage all platform users</p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form action="/admin/users" method="get" role="search" className="space-y-2">
            <Label htmlFor="user-search">Search users by name or email</Label>
            <div className="flex items-center gap-3">
              <div className="relative flex-1">
                <Search
                  aria-hidden="true"
                  className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  key={query ?? ''}
                  id="user-search"
                  type="search"
                  placeholder="Search users by email or name..."
                  className="pl-10"
                  name="q"
                  maxLength={MAX_QUERY_LENGTH}
                  defaultValue={query}
                />
              </div>
              <Button type="submit" variant="outline">
                Search
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <Suspense
            key={`${query ?? ''}:${page}`}
            fallback={<TableSkeleton columns={USERS_COLUMNS} label="Loading users" />}
          >
            <UsersResults query={query} page={page} />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
