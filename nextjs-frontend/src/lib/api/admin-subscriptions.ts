import 'server-only';

import { callBackend } from './server';
import { adminListSubscriptions, type AdminListSubscriptionsData } from './generated';

/**
 * Server-only call to the admin subscriptions API (KAN-48, `/v1/admin/subscriptions`) for the admin
 * subscriptions page (KAN-50). The backend authenticates the session and checks the admin permission on
 * every call. Subscriptions belong to organisations.
 */

type SubscriptionQuery = NonNullable<AdminListSubscriptionsData['query']>;

export function fetchAdminSubscriptions(params: {
  status?: SubscriptionQuery['status'];
  plan?: SubscriptionQuery['plan'];
  limit?: number;
  offset?: number;
}) {
  return callBackend((client) =>
    adminListSubscriptions({
      client,
      query: {
        limit: params.limit ?? 20,
        offset: params.offset ?? 0,
        ...(params.status ? { status: params.status } : {}),
        ...(params.plan ? { plan: params.plan } : {}),
      },
    })
  );
}
