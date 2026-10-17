'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Input } from '@/components/ui/input';
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

/**
 * The current page of products. The text box narrows only the rows already loaded on this page: the API has no
 * text search yet, so it never queries the server and says so next to the box.
 */
export function ProductTable({ rows }: { rows: ReadonlyArray<ProductRow> }) {
  const [filter, setFilter] = useState('');
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? rows.filter((row) => `${row.title} ${row.slug}`.toLowerCase().includes(needle))
    : rows;

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="product-page-filter" className="mb-1 block text-sm font-medium">
          Filter this page by title
        </label>
        <Input
          id="product-page-filter"
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          maxLength={100}
          className="max-w-sm"
          aria-describedby="product-page-filter-hint"
        />
        <p id="product-page-filter-hint" className="mt-1 text-xs text-muted-foreground">
          Only narrows the products shown on this page. Store-wide search is not available yet.
        </p>
      </div>
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
          {visible.map((row) => (
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
      {visible.length === 0 && (
        <p role="status" className="py-4 text-center text-sm text-muted-foreground">
          No products on this page match the filter.
        </p>
      )}
    </div>
  );
}
