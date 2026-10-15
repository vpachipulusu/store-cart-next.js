import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { adminErrorMessage } from '@/lib/api/admin-users';
import { fetchAdminAuditLogs } from '@/lib/api/admin-audit-logs';
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
          <CardDescription>Last 100 audit log entries</CardDescription>
        </CardHeader>
        <CardContent>
          {!result.success ? (
            <p role="alert" className="py-8 text-center text-sm text-destructive">
              {adminErrorMessage(result)}
            </p>
          ) : logs.length > 0 ? (
            <Table>
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
                      {log.user_id || '—'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {log.ip_address || '—'}
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
