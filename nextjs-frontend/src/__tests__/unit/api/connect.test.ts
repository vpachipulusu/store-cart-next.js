// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  cookieGet: vi.fn(),
  getCurrentStoreSelection: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: mocks.cookieGet })),
  headers: vi.fn(async () => ({ get: vi.fn() })),
}));
vi.mock('@/lib/stores/current', () => ({
  getCurrentStoreSelection: mocks.getCurrentStoreSelection,
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

function selectionOf(organizationId: string) {
  const selected = {
    id: `store-of-${organizationId}`,
    name: 'Shop',
    slug: 'shop',
    status: 'ACTIVE',
    organizationId,
    organizationName: organizationId,
  };
  return { available: true, stores: [selected], selected };
}

describe('Connect API wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    process.env.BACKEND_API_URL = BACKEND_URL;
    mocks.cookieGet.mockReturnValue({ name: 'session', value: 'session-cookie' });
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-1'));
    fetchMock.mockReset().mockImplementation(async (request) =>
      request.url.endsWith('/onboarding-link')
        ? jsonResponse({ success: true, data: { url: 'https://connect.stripe.test/x' } })
        : jsonResponse({
            success: true,
            data: {
              has_account: true,
              charges_enabled: false,
              payouts_enabled: false,
              details_submitted: true,
            },
          })
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reads the status for the organisation that owns the selected store', async () => {
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
    const [[request]] = fetchMock.mock.calls;
    expect(request.method).toBe('GET');
    expect(request.url).toBe(`${BACKEND_URL}/v1/organizations/org-1/connect`);
    expect(request.headers.get('X-Session-Token')).toBe('session-cookie');
  });

  it('follows the selected store when the user belongs to several organisations', async () => {
    // A user who owns org-a and administers org-b is looking at a store of org-b.
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-b'));

    await fetchConnectStatus();
    await startConnectOnboarding('https://app.test/r', 'https://app.test/f');

    expect(fetchMock.mock.calls.map(([request]) => request.url)).toEqual([
      `${BACKEND_URL}/v1/organizations/org-b/connect`,
      `${BACKEND_URL}/v1/organizations/org-b/connect/onboarding-link`,
    ]);
  });

  it('sends the return and refresh URLs and no client idempotency key', async () => {
    const result = await startConnectOnboarding('https://app.test/r', 'https://app.test/f');

    expect(result).toEqual({ success: true, data: { url: 'https://connect.stripe.test/x' } });
    const [[request]] = fetchMock.mock.calls;
    expect(request.method).toBe('POST');
    expect(await request.clone().json()).toEqual({
      return_url: 'https://app.test/r',
      refresh_url: 'https://app.test/f',
    });
    expect(request.headers.get('Idempotency-Key')).toBeNull();
  });

  it('does not call the backend when the user has no store', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: true,
      stores: [],
      selected: null,
    });

    const result = await fetchConnectStatus();

    expect(result).toEqual({ success: false, error: NO_CONNECT_ORGANIZATION_MESSAGE });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('passes on the error when the store list is unavailable', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue({
      available: false,
      error: 'Could not load your stores. Please try again.',
    });

    const result = await fetchConnectStatus();

    expect(result).toEqual({
      success: false,
      error: 'Could not load your stores. Please try again.',
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('passes a backend error through with its status', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ success: false, error: 'Forbidden' }, 403)
    );

    const result = await fetchConnectStatus();

    expect(result).toEqual({ success: false, error: 'Forbidden', status: 403 });
  });
});
