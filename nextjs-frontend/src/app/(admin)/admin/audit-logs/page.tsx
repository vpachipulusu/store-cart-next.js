import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { adminErrorMessage } from '@/lib/api/admin-errors';
import { AUDIT_LOG_PAGE_SIZE, fetchAdminAuditLogs } from '@/lib/api/admin-audit-logs';
import { EmptyCell } from '../_components/empty-cell';
import { logger } from '@/lib/logger';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

export default async function AdminAuditLogsPage() {
  const result = await fetchAdminAuditLogs();
  if (!result.success) {
    logger.error('Admin audit logs page: list failed', { status: result.status });
  }
  const logs = result.success ? result.data.entries : [];
  const totalCount = result.success ? result.data.total_count : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Audit Logs</h1>
        <p className="text-muted-foreground">Track all administrative actions and system events</p>
      </div>

      {/* Logs Table */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Activity</CardTitle>
          <CardDescription>
            {result.success
              ? `Showing ${logs.length} of ${totalCount} entries (newest first, up to ${AUDIT_LOG_PAGE_SIZE})`
              : 'Audit log entries'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!result.success ? (
            <p role="alert" className="py-8 text-center text-sm text-destructive">
              {adminErrorMessage(result)}
            </p>
          ) : logs.length > 0 ? (
            <Table aria-label="Audit log entries">
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>User ID</TableHead>
                  <TableHead>IP Address</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(log.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{log.action}</Badge>
                    </TableCell>
                    <TableCell className="font-medium">{log.resource}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {log.user_id || <EmptyCell />}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {log.ip_address || <EmptyCell />}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No audit logs found</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
