import 'server-only';

import { callBackend } from './server';
import { createOnboardingLink, readConnectStatus } from './generated';
import { getCurrentStoreSelection } from '@/lib/stores/current';

/**
 * Server-only calls to the organisation Stripe Connect API (KAN-67). Server actions import these instead of the
 * generated SDK (ADR-008).
 *
 * The organisation is the one that owns the dashboard's selected store: `getCurrentStoreSelection()` validates the
 * `selected-store` cookie against the caller's own stores on every request. A user who owns one organisation and
 * administers another therefore sets up payments for the organisation they are looking at, never "the first one".
 * The backend authorises the organisation id again for the caller's role. Return URLs are built by the action,
 * never taken from the browser.
 */

export const NO_CONNECT_ORGANIZATION_MESSAGE =
  'No organisation you can set up payments for was found';

async function withOrganization<T>(
  call: (organizationId: string) => Promise<T>
): Promise<T | { success: false; error: string; status?: number }> {
  const selection = await getCurrentStoreSelection();
  if (!selection.available) return { success: false, error: selection.error };
  if (!selection.selected) return { success: false, error: NO_CONNECT_ORGANIZATION_MESSAGE };
  return call(selection.selected.organizationId);
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
        body: { return_url: returnUrl, refresh_url: refreshUrl },
      })
    )
  );
}
