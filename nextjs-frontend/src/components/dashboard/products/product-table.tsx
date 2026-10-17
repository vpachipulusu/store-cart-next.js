import Link from 'next/link';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ProductStatus } from '@/lib/products/schema';
import { ProductStatusPill } from './product-status-pill';

export type ProductRow = {
  id: string;
  title: string;
  slug: string;
  status: ProductStatus;
  variantCount: number;
  /** Already formatted in the store currency; null when the product has no priced variant. */
  price: string | null;
  updated: string;
};

/** The current page of products. Search and filters run on the server, so this only renders the rows. */
export function ProductTable({ rows }: { rows: ReadonlyArray<ProductRow> }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Product</TableHead>
          <TableHead>Status</TableHead>
          <TableHead numeric>Variants</TableHead>
          <TableHead numeric>Price</TableHead>
          <TableHead>Updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-testid="product-row">
            <TableCell className="font-medium">
              <Link
                href={`/dashboard/products/${row.id}`}
                className="inline-flex min-h-11 items-center underline-offset-4 hover:underline"
              >
                {row.title}
              </Link>
              <span className="block text-xs font-normal text-muted-foreground">{row.slug}</span>
            </TableCell>
            <TableCell label="Status">
              <ProductStatusPill status={row.status} />
            </TableCell>
            <TableCell numeric label="Variants">
              {row.variantCount}
            </TableCell>
            <TableCell numeric label="Price">
              {row.price ?? '—'}
            </TableCell>
            <TableCell label="Updated">{row.updated}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
