import { Download, ExternalLink } from 'lucide-react';

import { InvoiceStatusPill } from '@/components/dashboard/billing/billing-pills';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export interface Invoice {
  id: string;
  /** Minor units (cents). */
  amount: number;
  currency: string;
  status: string;
  created: string;
  pdfUrl: string | null;
  hostedUrl: string | null;
}

function formatAmount(amount: number, currency: string): string {
  try {
    return (amount / 100).toLocaleString('en-US', { style: 'currency', currency });
  } catch {
    // Unknown currency code from the provider: show the number rather than crash the page.
    return `${(amount / 100).toFixed(2)} ${currency.toUpperCase()}`;
  }
}

export function InvoiceTable({ invoices }: { invoices: ReadonlyArray<Invoice> }) {
  return (
    <Table stacked aria-label="Invoices">
      <TableCaption>Your recent invoices and payments</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead numeric>Amount</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>
            <span className="sr-only">Documents</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoices.map((invoice) => (
          <TableRow key={invoice.id}>
            <TableCell label="Date">{new Date(invoice.created).toLocaleDateString()}</TableCell>
            <TableCell label="Amount" numeric>
              {formatAmount(invoice.amount, invoice.currency)}
            </TableCell>
            <TableCell label="Status">
              <InvoiceStatusPill status={invoice.status} />
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-1">
                {invoice.pdfUrl && (
                  <Button variant="ghost" asChild>
                    <a href={invoice.pdfUrl} target="_blank" rel="noopener noreferrer">
                      <Download className="h-4 w-4" aria-hidden="true" />
                      <span className="ml-1">PDF</span>
                    </a>
                  </Button>
                )}
                {invoice.hostedUrl && (
                  <Button variant="ghost" asChild>
                    <a href={invoice.hostedUrl} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-4 w-4" aria-hidden="true" />
                      <span className="ml-1">View</span>
                    </a>
                  </Button>
                )}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
