import { adminErrorMessage } from '@/lib/api/admin-errors';
import { fetchAdminSystemStats, type SystemData } from '@/lib/api/admin-analytics';
import { logger } from '@/lib/logger';
import { Panel } from '@/components/dashboard/overview/panel';
import { RefreshButton } from '@/components/admin/refresh-button';
import { InlineError } from '../_components/inline-error';
import { formatCount } from '../_components/format-money';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const SETTINGS_HREF = '/admin/settings';
const LABELS: ReadonlyArray<readonly [keyof SystemData, string]> = [
  ['app_settings', 'Application settings'],
  ['feature_flags', 'Feature flags'],
  ['email_templates', 'Email templates'],
  ['seo_entries', 'SEO entries'],
  ['redirects', 'URL redirects'],
  ['audit_logs', 'Audit log entries'],
  ['stripe_events', 'Stripe events processed'],
  ['admin_users', 'Platform admins'],
];

export default async function AdminSettingsPage() {
  const stats = await fetchAdminSystemStats();
  if (!stats.success) {
    logger.error('Admin settings page: system stats failed', { status: stats.status });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
          <p className="text-muted-foreground">
            System statistics. Editing settings, flags and templates is not available yet.
          </p>
        </div>
        <RefreshButton />
      </div>

      {stats.success ? (
        <Panel title="System stats" titleId="admin-system-stats">
          <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
            {LABELS.map(([key, label]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-right tabular-nums">{formatCount(stats.data[key])}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      ) : (
        <InlineError message={adminErrorMessage(stats)} retryHref={SETTINGS_HREF} />
      )}
    </div>
  );
}
