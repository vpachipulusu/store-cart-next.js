import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { fetchAdminSubscriptions } from '@/lib/api/admin-subscriptions';
import { EmptyCell } from '../_components/empty-cell';
import { formatAdminDate } from '../_components/format-admin-date';
import { PlanPill, SubscriptionStatusPill } from './subscription-pills';

type SubscriptionsResult = Awaited<ReturnType<typeof fetchAdminSubscriptions>>;
export type SubscriptionRow = (SubscriptionsResult extends infer R
  ? Extract<R, { success: true }>
  : never)['data']['subscriptions'][number];

const SUBSCRIPTION_COLUMNS = ['Organisation', 'Slug', 'Plan', 'Status', 'Renewal Date', 'Actions'];

export function SubscriptionsTable({ subscriptions }: { subscriptions: SubscriptionRow[] }) {
  return (
    <Table stacked aria-label="Newest paid organisations">
      <TableHeader>
        <TableRow>
          {SUBSCRIPTION_COLUMNS.map((column) => (
            <TableHead key={column} className={column === 'Actions' ? 'text-right' : undefined}>
              {column}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {subscriptions.map((subscription) => (
          <TableRow key={subscription.organization_id}>
            <TableCell className="font-medium max-sm:w-full">{subscription.name}</TableCell>
            <TableCell label="Slug" className="text-muted-foreground">
              {subscription.slug}
            </TableCell>
            <TableCell label="Plan">
              <PlanPill plan={subscription.plan} />
            </TableCell>
            <TableCell label="Status">
              <SubscriptionStatusPill status={subscription.status} />
            </TableCell>
            <TableCell label="Renewal Date" className="text-muted-foreground">
              {subscription.current_period_end ? (
                formatAdminDate(subscription.current_period_end)
              ) : (
                <EmptyCell />
              )}
            </TableCell>
            <TableCell className="text-right">
              <Button variant="ghost" size="sm" aria-label={`Manage ${subscription.name}`}>
                Manage
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
