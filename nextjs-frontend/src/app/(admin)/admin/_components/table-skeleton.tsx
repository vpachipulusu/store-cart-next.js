import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type TableSkeletonProps = {
  /** Column headings, shown as-is so the table does not shift when data arrives. */
  columns: string[];
  /** Accessible name announced while loading. */
  label: string;
  rows?: number;
};

const DEFAULT_ROWS = 8;

/** Loading state for admin tables: real header, skeleton body rows. */
export function TableSkeleton({ columns, label, rows = DEFAULT_ROWS }: TableSkeletonProps) {
  return (
    <div aria-busy="true">
      <p role="status" className="sr-only">
        {label}
      </p>
      <Table stacked>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rows }, (_, row) => (
            <TableRow key={row}>
              {columns.map((column) => (
                <TableCell key={column}>
                  <Skeleton className="h-5 w-32" />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
