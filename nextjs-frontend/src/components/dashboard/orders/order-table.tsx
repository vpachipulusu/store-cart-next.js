import Link from 'next/link';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { OrderStatus } from '@/lib/orders/schema';
import { OrderStatusPill } from './order-status-pill';

export type OrderRow = {
  id: string;
  status: OrderStatus;
  /** Already formatted in the order currency. */
  total: string;
  itemCount: number;
  tracking: string | null;
  placed: string;
};

/** The current page of orders. Filters run on the server, so this only renders the rows. */
export function OrderTable({ rows }: { rows: ReadonlyArray<OrderRow> }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead>Status</TableHead>
          <TableHead numeric>Items</TableHead>
          <TableHead numeric>Total</TableHead>
          <TableHead>Tracking</TableHead>
          <TableHead>Placed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-testid="order-row">
            <TableCell className="font-medium">
              <Link
                href={`/dashboard/orders/${row.id}`}
                className="inline-flex min-h-11 items-center font-mono text-xs underline-offset-4 hover:underline"
              >
                {row.id}
              </Link>
            </TableCell>
            <TableCell label="Status">
              <OrderStatusPill status={row.status} />
            </TableCell>
            <TableCell numeric label="Items">
              {row.itemCount}
            </TableCell>
            <TableCell numeric label="Total">
              {row.total}
            </TableCell>
            <TableCell label="Tracking">{row.tracking ?? '—'}</TableCell>
            <TableCell label="Placed">{row.placed}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
