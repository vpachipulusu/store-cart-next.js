import 'server-only';

import { callBackend } from './server';
import { adminOverview, adminRevenue, adminSystemStats, adminSyncSubscriptions } from './generated';

export type { OverviewData, RevenueData, SyncData, SystemData } from './generated';

/**
 * Server-only calls to the platform analytics API (KAN-119, `/v1/admin/analytics`) for the admin analytics,
 * subscriptions and settings pages. The backend authenticates the session and checks the admin permission on
 * every call (overview: users.read, revenue: subscriptions.read, system: settings.read, sync:
 * subscriptions.sync). Revenue is in minor units of the platform currency.
 */

export function fetchAdminOverview() {
  return callBackend((client) => adminOverview({ client }));
}

export function fetchAdminRevenue() {
  return callBackend((client) => adminRevenue({ client }));
}

export function fetchAdminSystemStats() {
  return callBackend((client) => adminSystemStats({ client }));
}

/** Reads every Stripe subscription and reports drift from the stored state. Writes one audit row only. */
export function syncAdminSubscriptions() {
  return callBackend((client) => adminSyncSubscriptions({ client }));
}
