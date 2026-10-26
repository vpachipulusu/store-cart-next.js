// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
  NO_TEAM_ORGANIZATION_MESSAGE,
  SELECTED_ORGANIZATION_MISSING_MESSAGE,
  acceptTeamInvitation,
  canManageTeam,
  createTeamInvitation,
  fetchTeam,
  isStaffOnlyMember,
  resolveTeamOrganization,
} from '@/lib/api/team';

const BACKEND_URL = 'http://backend.test';
const LINK = 'https://app.test/invite/secret-token-value-123456789';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function organization(id: string, role: string) {
  return {
    id,
    name: `Org ${id}`,
    slug: id,
    role,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    stores: [],
    stores_truncated: false,
  };
}

function selectionOf(organizationId: string | null) {
  if (!organizationId) return { available: true, stores: [], selected: null };
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

const MEMBER = {
  user_id: 'u1',
  email: 'owner@example.com',
  display_name: null,
  role: 'OWNER',
  joined_at: '2026-10-01T00:00:00Z',
};
const INVITATION = {
  id: 'inv1',
  email: 'new@example.com',
  role: 'STAFF',
  expires_at: '2026-11-01T00:00:00Z',
  created_at: '2026-10-25T00:00:00Z',
};

describe('team API wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  let organizations = [organization('org-a', 'OWNER'), organization('org-b', 'STAFF')];

  beforeEach(() => {
    process.env.BACKEND_API_URL = BACKEND_URL;
    organizations = [organization('org-a', 'OWNER'), organization('org-b', 'STAFF')];
    mocks.cookieGet.mockReturnValue({ name: 'session', value: 'session-cookie' });
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-a'));
    fetchMock.mockReset().mockImplementation(async (request) => {
      const { pathname } = new URL(request.url);
      if (pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: organizations,
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (pathname.endsWith('/members')) {
        return jsonResponse({ success: true, data: [MEMBER], total: 1, limit: 100, offset: 0 });
      }
      if (pathname.endsWith('/invitations') && request.method === 'GET') {
        return jsonResponse({ success: true, data: [INVITATION] });
      }
      if (pathname.endsWith('/invitations')) {
        return jsonResponse(
          { success: true, data: { ...INVITATION, accept_url: LINK, email_sent: true } },
          201
        );
      }
      if (pathname === '/v1/invitations/accept') {
        return jsonResponse({ success: true, data: { organization_id: 'org-a', role: 'STAFF' } });
      }
      return jsonResponse({ success: false, error: 'Not found' }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('only owners and admins manage the team', () => {
    expect(canManageTeam('OWNER')).toBe(true);
    expect(canManageTeam('ADMIN')).toBe(true);
    expect(canManageTeam('STAFF')).toBe(false);
  });

  it('resolves the role in the organisation of the selected store', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-b'));

    expect(await resolveTeamOrganization()).toEqual({
      success: true,
      data: { id: 'org-b', name: 'Org org-b', role: 'STAFF' },
    });
  });

  it('is not truncated when a full page is all there is', async () => {
    const full = Array.from({ length: 100 }, (_, n) => ({ ...MEMBER, user_id: `u${n}` }));
    fetchMock.mockImplementation(async (request) => {
      const { pathname } = new URL(request.url);
      if (pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: organizations,
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (pathname.endsWith('/members')) {
        return jsonResponse({ success: true, data: full, total: 100, limit: 100, offset: 0 });
      }
      return jsonResponse({ success: true, data: [] });
    });

    const result = await fetchTeam();

    expect(result.success && result.data.members).toHaveLength(100);
    expect(result.success && result.data.membersTruncated).toBe(false);
  });

  it('marks the members as truncated when the total is larger than the page', async () => {
    const full = Array.from({ length: 100 }, (_, n) => ({ ...MEMBER, user_id: `u${n}` }));
    fetchMock.mockImplementation(async (request) => {
      const { pathname } = new URL(request.url);
      if (pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: organizations,
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (pathname.endsWith('/members')) {
        return jsonResponse({ success: true, data: full, total: 120, limit: 100, offset: 0 });
      }
      return jsonResponse({ success: true, data: [] });
    });

    const result = await fetchTeam();

    expect(result.success && result.data.membersTruncated).toBe(true);
  });

  it('fails instead of guessing when the selected store’s organisation is missing', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-gone'));

    expect(await resolveTeamOrganization()).toEqual({
      success: false,
      error: SELECTED_ORGANIZATION_MISSING_MESSAGE,
    });
    expect(await createTeamInvitation('x@example.com', 'STAFF')).toEqual({
      success: false,
      error: SELECTED_ORGANIZATION_MISSING_MESSAGE,
    });
  });

  it('falls back to an organisation the user manages when they have no store', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf(null));
    organizations = [organization('org-b', 'STAFF'), organization('org-a', 'ADMIN')];

    const result = await resolveTeamOrganization();

    expect(result).toEqual({
      success: true,
      data: { id: 'org-a', name: 'Org org-a', role: 'ADMIN' },
    });
  });

  it('falls back to any membership, then to none', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf(null));
    organizations = [organization('org-b', 'STAFF')];
    expect((await resolveTeamOrganization()).success && true).toBe(true);
    expect(await resolveTeamOrganization()).toMatchObject({ data: { role: 'STAFF' } });

    organizations = [];
    expect(await resolveTeamOrganization()).toEqual({ success: true, data: null });
  });

  it('passes on an unavailable store list or organisation list', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValueOnce({ available: false, error: 'No stores' });
    expect(await resolveTeamOrganization()).toEqual({ success: false, error: 'No stores' });

    fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'Boom' }, 500));
    expect(await resolveTeamOrganization()).toEqual({ success: false, error: 'Boom', status: 500 });
  });

  it.each([
    ['STAFF everywhere', [organization('org-b', 'STAFF')], true],
    ['STAFF and OWNER', [organization('org-b', 'STAFF'), organization('org-a', 'OWNER')], false],
    ['no memberships', [], false],
  ])('isStaffOnlyMember: %s', async (_label, memberships, expected) => {
    organizations = memberships;

    expect(await isStaffOnlyMember()).toEqual({ success: true, data: expected });
  });

  it('isStaffOnlyMember passes on a failed lookup', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'Boom' }, 500));

    expect(await isStaffOnlyMember()).toEqual({ success: false, error: 'Boom', status: 500 });
  });

  it('loads members and pending invitations of the managed organisation', async () => {
    const result = await fetchTeam();

    expect(result).toEqual({
      success: true,
      data: {
        organization: { id: 'org-a', name: 'Org org-a', role: 'OWNER' },
        members: [MEMBER],
        membersTruncated: false,
        invitations: [INVITATION],
      },
    });
    const urls = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname);
    expect(urls).toContain('/v1/organizations/org-a/members');
    const members = fetchMock.mock.calls
      .map(([request]) => new URL(request.url))
      .find((url) => url.pathname.endsWith('/members'))!;
    expect(members.searchParams.get('limit')).toBe('100');
    expect(urls).toContain('/v1/organizations/org-a/invitations');
  });

  it('does not call the team routes for a STAFF member', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf('org-b'));

    expect(await fetchTeam()).toEqual({ success: false, error: 'Forbidden', status: 403 });
    expect(await createTeamInvitation('x@example.com', 'STAFF')).toMatchObject({ status: 403 });
    const urls = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname);
    expect(urls.every((url) => url === '/v1/organizations')).toBe(true);
  });

  it('reports no organisation without calling the team routes', async () => {
    mocks.getCurrentStoreSelection.mockResolvedValue(selectionOf(null));
    organizations = [];

    expect(await fetchTeam()).toEqual({ success: false, error: NO_TEAM_ORGANIZATION_MESSAGE });
  });

  it('passes on a failed member or invitation list', async () => {
    fetchMock.mockImplementation(async (request) => {
      const { pathname } = new URL(request.url);
      if (pathname === '/v1/organizations') {
        return jsonResponse({
          success: true,
          data: organizations,
          total: 2,
          limit: 100,
          offset: 0,
        });
      }
      if (pathname.endsWith('/members')) return jsonResponse({ success: true, data: [MEMBER] });
      return jsonResponse({ success: false, error: 'Forbidden' }, 403);
    });
    expect(await fetchTeam()).toEqual({ success: false, error: 'Forbidden', status: 403 });

    fetchMock.mockImplementation(async (request) =>
      new URL(request.url).pathname === '/v1/organizations'
        ? jsonResponse({ success: true, data: organizations, total: 2, limit: 100, offset: 0 })
        : jsonResponse({ success: false, error: 'Nope' }, 404)
    );
    expect(await fetchTeam()).toEqual({ success: false, error: 'Nope', status: 404 });
  });

  it('creates an invitation for the managed organisation', async () => {
    const result = await createTeamInvitation('new@example.com', 'ADMIN');

    expect(result).toMatchObject({ success: true, data: { accept_url: LINK, email_sent: true } });
    const request = fetchMock.mock.calls.at(-1)![0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe('/v1/organizations/org-a/invitations');
    expect(await request.clone().json()).toEqual({ email: 'new@example.com', role: 'ADMIN' });
  });

  it('accepts with the token in the POST body, never in the URL', async () => {
    const result = await acceptTeamInvitation('secret-token-value-123456789');

    expect(result).toEqual({ success: true, data: { organization_id: 'org-a', role: 'STAFF' } });
    const [[request]] = fetchMock.mock.calls;
    expect(request.method).toBe('POST');
    expect(request.url).toBe(`${BACKEND_URL}/v1/invitations/accept`);
    expect(await request.clone().json()).toEqual({ token: 'secret-token-value-123456789' });
    expect(request.headers.get('X-Session-Token')).toBe('session-cookie');
  });
});
