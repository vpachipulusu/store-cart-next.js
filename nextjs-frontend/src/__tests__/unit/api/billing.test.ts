// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  NO_BILLING_ORGANIZATION_MESSAGE,
  cancelBillingSubscription,
  changeBillingPlan,
  fetchBillingInvoices,
  fetchBillingPaymentMethods,
  fetchBillingSummary,
  pickBillingOrganization,
  resumeBillingSubscription,
  startBillingCheckout,
  startBillingPortal,
} from '@/lib/api/billing';
import type { OrganizationData } from '@/lib/api/generated';

const BACKEND_URL = 'http://backend.test';

function organization(id: string, role: OrganizationData['role']): OrganizationData {
  return {
    id,
    name: id,
    slug: id,
    role,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    stores: [],
    stores_truncated: false,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('pickBillingOrganization', () => {
  it('prefers an owned organisation over an administered one', () => {
    const picked = pickBillingOrganization([
      organization('org-admin', 'ADMIN'),
      organization('org-staff', 'STAFF'),
      organization('org-owner', 'OWNER'),
    ]);
    expect(picked?.id).toBe('org-owner');
  });

  it('falls back to an administered organisation', () => {
    expect(
      pickBillingOrganization([organization('s', 'STAFF'), organization('a', 'ADMIN')])?.id
    ).toBe('a');
  });

  it('returns nothing for staff-only or empty memberships', () => {
    expect(pickBillingOrganization([organization('s', 'STAFF')])).toBeUndefined();
    expect(pickBillingOrganization([])).toBeUndefined();
  });
});

describe('billing API wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  let organizations: OrganizationData[];

  const billingCalls = () =>
    fetchMock.mock.calls.map(([request]) => request).filter((r) => r.url.includes('/billing'));

  beforeEach(() => {
    process.env.BACKEND_API_URL = BACKEND_URL;
    cookieGet.mockReturnValue({ name: 'session', value: 'session-cookie' });
    organizations = [organization('org-1', 'OWNER')];
    fetchMock.mockReset().mockImplementation(async (request) => {
      if (request.url === `${BACKEND_URL}/v1/organizations`) {
        return jsonResponse({
          success: true,
          data: organizations,
          total: organizations.length,
          limit: 50,
          offset: 0,
        });
      }
      if (request.url.endsWith('/payment-methods') || request.url.endsWith('/invoices')) {
        return jsonResponse({ success: true, data: [] });
      }
      if (request.url.endsWith('/checkout') || request.url.endsWith('/portal')) {
        return jsonResponse({ success: true, data: { url: 'https://stripe.test/x' } });
      }
      return jsonResponse({ success: true, data: { plan: { key: 'free' } } });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reads the summary for the organisation taken from the session memberships', async () => {
    const result = await fetchBillingSummary();

    expect(result.success).toBe(true);
    const [request] = billingCalls();
    expect(request.method).toBe('GET');
    expect(request.url).toBe(`${BACKEND_URL}/v1/organizations/org-1/billing`);
    expect(request.headers.get('X-Session-Token')).toBe('session-cookie');
  });

  it('reads invoices and payment methods from the organisation routes', async () => {
    await fetchBillingInvoices();
    await fetchBillingPaymentMethods();

    expect(billingCalls().map((r) => r.url)).toEqual([
      `${BACKEND_URL}/v1/organizations/org-1/billing/invoices`,
      `${BACKEND_URL}/v1/organizations/org-1/billing/payment-methods`,
    ]);
  });

  it('sends checkout with a body and a fresh Idempotency-Key', async () => {
    const first = await startBillingCheckout(
      'pro',
      'yearly',
      'https://app.test/ok',
      'https://app.test/no'
    );
    await startBillingCheckout('pro', 'yearly', 'https://app.test/ok', 'https://app.test/no');

    expect(first).toEqual({ success: true, data: { url: 'https://stripe.test/x' } });
    const [one, two] = billingCalls();
    expect(one.method).toBe('POST');
    expect(one.url).toBe(`${BACKEND_URL}/v1/organizations/org-1/billing/checkout`);
    expect(await one.clone().json()).toEqual({
      plan: 'pro',
      interval: 'yearly',
      success_url: 'https://app.test/ok',
      cancel_url: 'https://app.test/no',
    });
    const key = one.headers.get('Idempotency-Key');
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(two.headers.get('Idempotency-Key')).not.toBe(key);
  });

  it('routes portal, plan change, cancel and resume to their endpoints', async () => {
    await startBillingPortal('https://app.test/billing');
    await changeBillingPlan('enterprise', 'monthly');
    await cancelBillingSubscription();
    await resumeBillingSubscription();

    expect(billingCalls().map((r) => `${r.method} ${r.url.replace(BACKEND_URL, '')}`)).toEqual([
      'POST /v1/organizations/org-1/billing/portal',
      'POST /v1/organizations/org-1/billing/plan',
      'POST /v1/organizations/org-1/billing/cancel',
      'POST /v1/organizations/org-1/billing/resume',
    ]);
  });

  it('does not call any billing route when the user manages no organisation', async () => {
    organizations = [organization('org-staff', 'STAFF')];

    const result = await startBillingPortal('https://app.test/billing');

    expect(result).toEqual({ success: false, error: NO_BILLING_ORGANIZATION_MESSAGE });
    expect(billingCalls()).toHaveLength(0);
  });

  it('passes through a backend error from the organisation lookup', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'Unauthorized' }, 401));

    const result = await fetchBillingSummary();

    expect(result).toMatchObject({ success: false, error: 'Unauthorized' });
    expect(billingCalls()).toHaveLength(0);
  });
});
