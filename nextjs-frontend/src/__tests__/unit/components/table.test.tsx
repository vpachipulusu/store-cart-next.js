import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  SortableTableHead,
} from '@/components/ui/table';

/** KAN-215: ledger table (caption, scope, numeric cells, stacked rows, aria-sort). */

function Sample({ stacked }: { stacked?: boolean }) {
  return (
    <Table stacked={stacked}>
      <TableCaption>Recent orders</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead numeric>Total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell label="Order">#1001</TableCell>
          <TableCell numeric label="Total">
            $12.00
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  );
}

describe('Table', () => {
  it('has a visually hidden caption that names the table', () => {
    render(<Sample />);
    const caption = screen.getByText('Recent orders');
    expect(caption.tagName).toBe('CAPTION');
    expect(caption.className).toContain('sr-only');
    expect(screen.getByRole('table', { name: 'Recent orders' })).toBeInTheDocument();
  });

  it('can show the caption visually', () => {
    render(
      <Table>
        <TableCaption visible>Shown</TableCaption>
      </Table>
    );
    expect(screen.getByText('Shown').className).not.toContain('sr-only');
  });

  it('gives every header scope="col" by default and allows override', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>A</TableHead>
            <TableHead scope="row">B</TableHead>
          </TableRow>
        </TableHeader>
      </Table>
    );
    expect(screen.getByText('A')).toHaveAttribute('scope', 'col');
    expect(screen.getByText('B')).toHaveAttribute('scope', 'row');
  });

  it('right-aligns numeric header and cells with tabular figures', () => {
    render(<Sample />);
    for (const el of [screen.getByText('Total'), screen.getByText('$12.00')]) {
      expect(el.className).toContain('text-right');
      expect(el.className).toContain('tabular-nums');
    }
    expect(screen.getByText('#1001').className).not.toContain('tabular-nums');
  });

  it('stacks rows below 640px and keeps labels for each cell', () => {
    render(<Sample />);
    const table = screen.getByRole('table');
    expect(table.className).toContain('max-sm:');
    expect(screen.getByText('$12.00')).toHaveAttribute('data-label', 'Total');
    // header stays in the accessibility tree (visually hidden only)
    expect(screen.getByText('Order', { selector: 'th' })).toBeInTheDocument();
  });

  it('does not stack when stacked is false', () => {
    render(<Sample stacked={false} />);
    expect(screen.getByRole('table').className).not.toContain('max-sm:');
  });

  it('keeps the className and aria-label passthrough for existing callers', () => {
    render(
      <Table aria-label="Audit log entries" className="extra">
        <TableBody />
      </Table>
    );
    expect(screen.getByRole('table', { name: 'Audit log entries' })).toHaveClass('extra');
  });
});

describe('SortableTableHead', () => {
  it.each(['ascending', 'descending', 'none'] as const)('exposes aria-sort=%s', (sort) => {
    render(
      <table>
        <thead>
          <tr>
            <SortableTableHead sort={sort} onSort={() => {}}>
              Joined
            </SortableTableHead>
          </tr>
        </thead>
      </table>
    );
    const th = screen.getByRole('columnheader');
    expect(th).toHaveAttribute('aria-sort', sort);
    expect(th).toHaveAttribute('scope', 'col');
  });

  it('is a 44px button that calls onSort', async () => {
    const onSort = vi.fn();
    render(
      <table>
        <thead>
          <tr>
            <SortableTableHead sort="none" onSort={onSort}>
              Joined
            </SortableTableHead>
          </tr>
        </thead>
      </table>
    );
    const btn = screen.getByRole('button', { name: /Joined/ });
    expect(btn.className).toContain('min-h-11');
    await userEvent.click(btn);
    expect(onSort).toHaveBeenCalledTimes(1);
  });
});
