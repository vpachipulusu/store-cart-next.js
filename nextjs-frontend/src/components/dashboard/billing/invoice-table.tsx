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

export function formatAmount(amount: number, currency: string): string {
  try {
    return (amount / 100).toLocaleString('en-US', { style: 'currency', currency });
  } catch {
    // Unknown currency code from the provider: show the number rather than crash the page.
    return `${(amount / 100).toFixed(2)} ${currency.toUpperCase()}`;
  }
}

/** Provider-supplied links are only rendered when they are https. */
function safeHttpsUrl(url: string | null): string | null {
  return url?.startsWith('https://') ? url : null;
}

export function InvoiceTable({ invoices }: { invoices: ReadonlyArray<Invoice> }) {
  return (
    <Table stacked>
      <TableCaption>Invoices</TableCaption>
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
        {invoices.map((invoice) => {
          const date = new Date(invoice.created).toLocaleDateString();
          const amount = formatAmount(invoice.amount, invoice.currency);
          const pdfUrl = safeHttpsUrl(invoice.pdfUrl);
          const hostedUrl = safeHttpsUrl(invoice.hostedUrl);
          return (
            <TableRow key={invoice.id}>
              <TableCell label="Date">{date}</TableCell>
              <TableCell label="Amount" numeric>
                {amount}
              </TableCell>
              <TableCell label="Status">
                <InvoiceStatusPill status={invoice.status} />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1">
                  {pdfUrl && (
                    <Button variant="ghost" asChild>
                      <a
                        href={pdfUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`PDF for invoice dated ${date}, ${amount} (opens in a new tab)`}
                      >
                        <Download className="h-4 w-4" aria-hidden="true" />
                        <span className="ml-1">PDF</span>
                      </a>
                    </Button>
                  )}
                  {hostedUrl && (
                    <Button variant="ghost" asChild>
                      <a
                        href={hostedUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`View invoice dated ${date}, ${amount} online (opens in a new tab)`}
                      >
                        <ExternalLink className="h-4 w-4" aria-hidden="true" />
                        <span className="ml-1">View</span>
                      </a>
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
