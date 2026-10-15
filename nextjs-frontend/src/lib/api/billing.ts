import 'server-only';

import { randomUUID } from 'node:crypto';
import { callBackend, type ApiResult } from './server';
import type { Client } from './generated/client';
import {
  cancelSubscription,
  changePlan,
  createCheckout,
  createPortal,
  deletePaymentMethod,
  listInvoices,
  listOrganizations,
  listPaymentMethods,
  readBilling,
  resumeSubscription,
  setDefaultPaymentMethod,
  type OrganizationData,
} from './generated';

/**
 * Server-only calls to the organisation billing API (KAN-43, KAN-45). Server actions import these instead of the
 * generated SDK (ADR-008). The organisation id is never taken from the browser: it comes from the caller's own
 * memberships (`GET /v1/organizations`, verified session), and the backend authorises every call again.
 */

export const NO_BILLING_ORGANIZATION_MESSAGE =
  'No organisation you can manage billing for was found';

type SdkResult<T> = { data?: T; error?: unknown; response?: Response };

/** Owners and admins manage billing; STAFF members cannot even read it (backend-org-billing.md). */
const BILLING_ROLES = ['OWNER', 'ADMIN'] as const;

export function pickBillingOrganization(
  organizations: ReadonlyArray<OrganizationData>
): OrganizationData | undefined {
  for (const role of BILLING_ROLES) {
    const match = organizations.find((organization) => organization.role === role);
    if (match) return match;
  }
  return undefined;
}

/** Resolves the organisation the signed-in user bills through; `data: null` when they manage none. */
export async function resolveBillingOrganizationId(): Promise<ApiResult<string | null>> {
  const result = await callBackend((client) => listOrganizations({ client }));
  if (!result.success) return result;
  return { success: true, data: pickBillingOrganization(result.data)?.id ?? null };
}

async function callBilling<TData>(
  call: (client: Client, organizationId: string) => Promise<SdkResult<TData>>
) {
  const organization = await resolveBillingOrganizationId();
  if (!organization.success) return organization;
  if (!organization.data) {
    return { success: false, error: NO_BILLING_ORGANIZATION_MESSAGE } as const;
  }
  const organizationId = organization.data;
  return callBackend((client) => call(client, organizationId));
}

/** A fresh key per user action makes a transport retry of that request replay-safe on the backend. */
function idempotencyHeaders() {
  return { 'Idempotency-Key': randomUUID() };
}

export function fetchBillingSummary() {
  return callBilling((client, organizationId) =>
    readBilling({ client, path: { organization_id: organizationId } })
  );
}

export function fetchBillingInvoices() {
  return callBilling((client, organizationId) =>
    listInvoices({ client, path: { organization_id: organizationId } })
  );
}

export function fetchBillingPaymentMethods() {
  return callBilling((client, organizationId) =>
    listPaymentMethods({ client, path: { organization_id: organizationId } })
  );
}

export function startBillingCheckout(
  plan: 'pro' | 'enterprise',
  interval: 'monthly' | 'yearly',
  successUrl: string,
  cancelUrl: string
) {
  return callBilling((client, organizationId) =>
    createCheckout({
      client,
      path: { organization_id: organizationId },
      headers: idempotencyHeaders(),
      body: { plan, interval, success_url: successUrl, cancel_url: cancelUrl },
    })
  );
}

export function startBillingPortal(returnUrl: string) {
  return callBilling((client, organizationId) =>
    createPortal({
      client,
      path: { organization_id: organizationId },
      headers: idempotencyHeaders(),
      body: { return_url: returnUrl },
    })
  );
}

export function changeBillingPlan(plan: 'pro' | 'enterprise', interval: 'monthly' | 'yearly') {
  return callBilling((client, organizationId) =>
    changePlan({
      client,
      path: { organization_id: organizationId },
      headers: idempotencyHeaders(),
      body: { plan, interval },
    })
  );
}

export function cancelBillingSubscription() {
  return callBilling((client, organizationId) =>
    cancelSubscription({
      client,
      path: { organization_id: organizationId },
      headers: idempotencyHeaders(),
    })
  );
}

export function resumeBillingSubscription() {
  return callBilling((client, organizationId) =>
    resumeSubscription({
      client,
      path: { organization_id: organizationId },
      headers: idempotencyHeaders(),
    })
  );
}

export function deleteBillingPaymentMethod(paymentMethodId: string) {
  return callBilling((client, organizationId) =>
    deletePaymentMethod({
      client,
      path: { organization_id: organizationId, payment_method_id: paymentMethodId },
      headers: idempotencyHeaders(),
    })
  );
}

export function setDefaultBillingPaymentMethod(paymentMethodId: string) {
  return callBilling((client, organizationId) =>
    setDefaultPaymentMethod({
      client,
      path: { organization_id: organizationId, payment_method_id: paymentMethodId },
      headers: idempotencyHeaders(),
    })
  );
}
