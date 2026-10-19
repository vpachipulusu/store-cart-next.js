// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const cookieGet = vi.fn();
vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));

import {
  NO_CONNECT_ORGANIZATION_MESSAGE,
  fetchConnectStatus,
  startConnectOnboarding,
} from '@/lib/api/connect';

const BACKEND_URL = 'http://backend.test';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function organization(id: string, role: 'OWNER' | 'ADMIN' | 'STAFF') {
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

describe('Connect API wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  let organizations: ReturnType<typeof organization>[];

  const connectCalls = () =>
    fetchMock.mock.calls.map(([request]) => request).filter((r) => r.url.includes('/connect'));

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
      if (request.url.endsWith('/onboarding-link')) {
        return jsonResponse({ success: true, data: { url: 'https://connect.stripe.test/x' } });
      }
      return jsonResponse({
        success: true,
        data: {
          has_account: true,
          charges_enabled: false,
          payouts_enabled: false,
          details_submitted: true,
        },
      });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reads the status for the organisation taken from the session memberships', async () => {
    const result = await fetchConnectStatus();

    expect(result).toEqual({
      success: true,
      data: {
        has_account: true,
        charges_enabled: false,
        payouts_enabled: false,
        details_submitted: true,
      },
    });
    const [request] = connectCalls();
    expect(request.method).toBe('GET');
    expect(request.url).toBe(`${BACKEND_URL}/v1/organizations/org-1/connect`);
    expect(request.headers.get('X-Session-Token')).toBe('session-cookie');
  });

  it('sends the return and refresh URLs with a fresh Idempotency-Key per call', async () => {
    const first = await startConnectOnboarding('https://app.test/r', 'https://app.test/f');
    await startConnectOnboarding('https://app.test/r', 'https://app.test/f');

    expect(first).toEqual({ success: true, data: { url: 'https://connect.stripe.test/x' } });
    const [one, two] = connectCalls();
    expect(one.method).toBe('POST');
    expect(one.url).toBe(`${BACKEND_URL}/v1/organizations/org-1/connect/onboarding-link`);
    expect(await one.clone().json()).toEqual({
      return_url: 'https://app.test/r',
      refresh_url: 'https://app.test/f',
    });
    const keyOne = one.headers.get('Idempotency-Key');
    expect(keyOne).toBeTruthy();
    expect(two.headers.get('Idempotency-Key')).not.toBe(keyOne);
  });

  it('does not call Connect for a user who owns or administers no organisation', async () => {
    organizations = [organization('org-staff', 'STAFF')];

    const result = await fetchConnectStatus();

    expect(result).toEqual({ success: false, error: NO_CONNECT_ORGANIZATION_MESSAGE });
    expect(connectCalls()).toHaveLength(0);
  });

  it('passes a backend error through with its status', async () => {
    fetchMock.mockImplementation(async (request) =>
      request.url.endsWith('/v1/organizations')
        ? jsonResponse({ success: true, data: organizations, total: 1, limit: 50, offset: 0 })
        : jsonResponse({ success: false, error: 'Forbidden' }, 403)
    );

    const result = await fetchConnectStatus();

    expect(result).toEqual({ success: false, error: 'Forbidden', status: 403 });
  });
});
