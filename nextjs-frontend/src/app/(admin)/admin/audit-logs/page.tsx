import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { adminErrorMessage } from '@/lib/api/admin-errors';
import { AUDIT_LOG_PAGE_SIZE, fetchAdminAuditLogs } from '@/lib/api/admin-audit-logs';
import { logger } from '@/lib/logger';
import { InlineError } from '../_components/inline-error';
import { AuditLogsTable } from './audit-logs-table';

const AUDIT_LOGS_HREF = '/admin/audit-logs';

export default async function AdminAuditLogsPage() {
  const result = await fetchAdminAuditLogs();
  if (!result.success) {
    logger.error('Admin audit logs page: list failed', { status: result.status });
  }
  const logs = result.success ? result.data.entries : [];
  const totalCount = result.success ? result.data.total_count : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Audit Logs</h1>
        <p className="text-muted-foreground">Track all administrative actions and system events</p>
      </div>

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
            <InlineError message={adminErrorMessage(result)} retryHref={AUDIT_LOGS_HREF} />
          ) : logs.length > 0 ? (
            <AuditLogsTable logs={logs} />
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">No audit logs found</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
