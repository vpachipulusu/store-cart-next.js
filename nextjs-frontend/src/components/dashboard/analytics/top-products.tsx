import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatMinor } from '@/lib/products/money';
import type { TopProductData } from '@/lib/api/analytics';

/** One top-10 ranking. Names are the ones saved on the orders, so deleted products still show. */
export function TopProducts({
  title,
  products,
  currency,
  testId,
}: {
  title: string;
  products: ReadonlyArray<TopProductData>;
  currency: string;
  testId: string;
}) {
  const headingId = `${testId}-heading`;
  return (
    <section aria-labelledby={headingId} className="min-w-0 space-y-2">
      <h3 id={headingId} className="text-sm font-medium">
        {title}
      </h3>
      {products.length === 0 ? (
        <p className="text-sm text-muted-foreground">No products sold in this period.</p>
      ) : (
        <Table stacked aria-labelledby={headingId} data-testid={testId}>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead numeric>Units</TableHead>
              <TableHead numeric>Revenue</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {products.map((product) => (
              <TableRow key={product.product_name} data-testid="top-product-row">
                <TableCell className="font-medium">{product.product_name}</TableCell>
                <TableCell numeric label="Units">
                  {product.units}
                </TableCell>
                <TableCell numeric label="Revenue">
                  {formatMinor(product.revenue_minor, currency)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
