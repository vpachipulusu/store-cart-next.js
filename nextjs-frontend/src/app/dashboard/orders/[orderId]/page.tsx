import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { FulfilForm } from '@/components/dashboard/orders/fulfil-form';
import { OrderStatusPill } from '@/components/dashboard/orders/order-status-pill';
import { ProductsLoadError } from '@/components/dashboard/products/products-load-error';
import { fetchOrder, orderErrorMessage, type OrderData } from '@/lib/api/orders';
import { formatMinor } from '@/lib/products/money';
import { isOrderId } from '@/lib/orders/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';

export const metadata = { title: 'Order' };

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
  timeZoneName: 'short',
});

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : DATE_TIME_FORMAT.format(date);
}

export default async function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = await params;
  if (!isOrderId(orderId)) notFound();

  const selection = await getCurrentStoreSelection();
  if (!selection.available || !selection.selected) return null;

  const result = await fetchOrder(selection.selected.id, orderId);
  if (!result.success && result.status === 404) notFound();

  return (
    <div className="space-y-6">
      <Link
        href="/dashboard/orders"
        className="inline-flex min-h-11 items-center text-sm text-muted-foreground underline-offset-4 hover:underline"
      >
        Back to orders
      </Link>
      {result.success ? (
        <OrderDetail order={result.data} />
      ) : (
        <>
          <h1 className="text-3xl font-bold tracking-tight">Order</h1>
          <ProductsLoadError
            message={orderErrorMessage(result)}
            retryHref={`/dashboard/orders/${orderId}`}
          />
        </>
      )}
    </div>
  );
}

function OrderDetail({ order }: { order: OrderData }) {
  const money = (minor: number) => formatMinor(minor, order.currency);
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-bold tracking-tight">Order</h1>
        <OrderStatusPill status={order.status} />
      </div>
      <p className="font-mono text-xs text-muted-foreground">{order.id}</p>

      <Card>
        <CardHeader>
          <CardTitle>Items</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead numeric>Price</TableHead>
                <TableHead numeric>Qty</TableHead>
                <TableHead numeric>Tax</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.items.map((item) => (
                <TableRow key={item.id} data-testid="order-item">
                  <TableCell className="font-medium">
                    {item.product_name}
                    {item.variant_label && (
                      <span className="block text-xs font-normal text-muted-foreground">
                        {item.variant_label}
                      </span>
                    )}
                  </TableCell>
                  <TableCell label="SKU">{item.sku}</TableCell>
                  <TableCell numeric label="Price">
                    {money(item.unit_price_minor)}
                  </TableCell>
                  <TableCell numeric label="Qty">
                    {item.quantity}
                  </TableCell>
                  <TableCell numeric label="Tax">
                    {money(item.tax_minor)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <dl className="ml-auto grid max-w-xs grid-cols-2 gap-x-4 gap-y-1 text-sm tabular-nums">
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd className="text-right">{money(order.subtotal_minor)}</dd>
            <dt className="text-muted-foreground">Tax</dt>
            <dd className="text-right">{money(order.tax_minor)}</dd>
            <dt className="font-semibold">Total</dt>
            <dd className="text-right font-semibold">{money(order.total_minor)}</dd>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Fulfilment</CardTitle>
        </CardHeader>
        <CardContent>
          {order.status === 'paid' ? (
            <FulfilForm orderId={order.id} />
          ) : order.tracking_number ? (
            <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted-foreground">Tracking number</dt>
              <dd data-testid="tracking-number">{order.tracking_number}</dd>
              <dt className="text-muted-foreground">Carrier</dt>
              <dd>{order.carrier ?? '—'}</dd>
              <dt className="text-muted-foreground">Fulfilled</dt>
              <dd>{formatDateTime(order.fulfilled_at)}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              {order.status === 'pending'
                ? 'This order can be fulfilled once it is paid.'
                : 'This order was not fulfilled.'}
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
