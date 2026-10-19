import 'server-only';

import { randomUUID } from 'node:crypto';
import { callBackend } from './server';
import { NO_BILLING_ORGANIZATION_MESSAGE, resolveBillingOrganizationId } from './billing';
import { createOnboardingLink, readConnectStatus } from './generated';

/**
 * Server-only calls to the organisation Stripe Connect API (KAN-67). Server actions import these instead of the
 * generated SDK (ADR-008). The organisation is the caller's own owner/admin organisation, the same one billing
 * uses; the backend authorises every call again. Return URLs are built by the action, never taken from the browser.
 */

export const NO_CONNECT_ORGANIZATION_MESSAGE = NO_BILLING_ORGANIZATION_MESSAGE;

async function withOrganization<T>(
  call: (organizationId: string) => Promise<T>
): Promise<T | { success: false; error: string; status?: number }> {
  const organization = await resolveBillingOrganizationId();
  if (!organization.success) return organization;
  if (!organization.data) {
    return { success: false, error: NO_CONNECT_ORGANIZATION_MESSAGE };
  }
  return call(organization.data);
}

export function fetchConnectStatus() {
  return withOrganization((organizationId) =>
    callBackend((client) =>
      readConnectStatus({ client, path: { organization_id: organizationId } })
    )
  );
}

export function startConnectOnboarding(returnUrl: string, refreshUrl: string) {
  return withOrganization((organizationId) =>
    callBackend((client) =>
      createOnboardingLink({
        client,
        path: { organization_id: organizationId },
        // A fresh key per click makes a transport retry of that click replay-safe on the backend.
        headers: { 'Idempotency-Key': randomUUID() },
        body: { return_url: returnUrl, refresh_url: refreshUrl },
      })
    )
  );
}
