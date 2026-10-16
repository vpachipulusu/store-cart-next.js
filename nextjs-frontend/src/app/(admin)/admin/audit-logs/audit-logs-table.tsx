import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { fetchAdminAuditLogs } from '@/lib/api/admin-audit-logs';
import { EmptyCell } from '../_components/empty-cell';
import { formatAdminDateTime } from '../_components/format-admin-date';

type AuditResult = Awaited<ReturnType<typeof fetchAdminAuditLogs>>;
export type AuditLogRow = (AuditResult extends infer R
  ? Extract<R, { success: true }>
  : never)['data']['entries'][number];

const AUDIT_COLUMNS = ['Timestamp', 'Action', 'Resource', 'User ID', 'IP Address'];

export function AuditLogsTable({ logs }: { logs: AuditLogRow[] }) {
  return (
    <Table stacked aria-label="Audit log entries">
      <TableHeader>
        <TableRow>
          {AUDIT_COLUMNS.map((column) => (
            <TableHead key={column}>{column}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {logs.map((log) => (
          <TableRow key={log.id}>
            <TableCell label="Timestamp" className="text-muted-foreground">
              {formatAdminDateTime(log.created_at)}
            </TableCell>
            <TableCell label="Action">
              <Badge variant="outline">{log.action}</Badge>
            </TableCell>
            <TableCell label="Resource" className="break-all font-medium">
              {log.resource}
            </TableCell>
            <TableCell label="User ID" className="break-all text-muted-foreground">
              {log.user_id || <EmptyCell />}
            </TableCell>
            <TableCell label="IP Address" className="text-muted-foreground">
              {log.ip_address || <EmptyCell />}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
