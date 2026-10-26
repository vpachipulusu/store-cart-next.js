import 'server-only';

import { cache } from 'react';
import { callBackend, type ApiResult } from './server';
import {
  acceptInvitation,
  createInvitation,
  listInvitations,
  listMembers,
  listOrganizations,
  type CreateInvitationRequest,
  type InvitationData,
  type MemberData,
  type MembershipRole,
} from './generated';
import { pickBillingOrganization } from './billing';
import { getCurrentStoreSelection } from '@/lib/stores/current';

/**
 * Server-only calls to the team members and invitations API (KAN-62). Server actions and server components import
 * these instead of the generated SDK (ADR-008).
 *
 * The organisation is the one that owns the dashboard's selected store (`getCurrentStoreSelection()`, validated
 * against the caller's own stores on every request), as for Connect. A user without stores falls back to an
 * organisation they own or administer. The caller's role comes from `GET /v1/organizations` (their memberships);
 * it decides what the page shows, and the backend authorises every call again (STAFF 403, non-member 404).
 */

export const NO_TEAM_ORGANIZATION_MESSAGE = 'No organisation was found for your account';
export const SELECTED_ORGANIZATION_MISSING_MESSAGE =
  'The organisation of the selected store could not be found';

/** The API's maximum page size; a user belongs to few organisations, so one page suffices. */
const ORGANIZATIONS_PAGE_SIZE = 100;
/** The members API's maximum page size; `membersTruncated` says the organisation has more. */
export const MEMBERS_PAGE_SIZE = 100;

/** The roles an invitation can carry, from the generated API types (OWNER is never invitable). */
export type InviteRole = CreateInvitationRequest['role'];
export type { MembershipRole };

export type TeamOrganization = { id: string; name: string; role: MembershipRole };

export type Team = {
  organization: TeamOrganization;
  members: ReadonlyArray<MemberData>;
  membersTruncated: boolean;
  invitations: ReadonlyArray<InvitationData>;
};

/** Owners and admins manage the team and billing; STAFF does neither. */
export function canManageTeam(role: MembershipRole): boolean {
  return role === 'OWNER' || role === 'ADMIN';
}

/** The caller's memberships with their role; deduplicated per request (the page and its helpers share one call). */
const listMyOrganizations = cache(() =>
  callBackend((client) => listOrganizations({ client, query: { limit: ORGANIZATIONS_PAGE_SIZE } }))
);

/** The organisation the dashboard is looking at and the caller's role in it; `data: null` when there is none. */
export const resolveTeamOrganization = cache(
  async (): Promise<ApiResult<TeamOrganization | null>> => {
    const selection = await getCurrentStoreSelection();
    if (!selection.available) return { success: false, error: selection.error };
    const result = await listMyOrganizations();
    if (!result.success) return result;
    const selectedId = selection.selected?.organizationId;
    if (selectedId) {
      // The store list and this list come from the same memberships; a miss means they changed in between.
      const selected = result.data.find((candidate) => candidate.id === selectedId);
      if (!selected) return { success: false, error: SELECTED_ORGANIZATION_MISSING_MESSAGE };
      return { success: true, data: { id: selected.id, name: selected.name, role: selected.role } };
    }
    const organization = pickBillingOrganization(result.data) ?? result.data[0];
    if (!organization) return { success: true, data: null };
    return {
      success: true,
      data: { id: organization.id, name: organization.name, role: organization.role },
    };
  }
);

/**
 * True when the caller belongs to organisations but manages none of them (STAFF everywhere). This is the billing
 * gate: billing shows the organisation the caller owns or administers (`pickBillingOrganization`, kept as is), so
 * an owner who is STAFF elsewhere still reaches their own billing, and a STAFF-only member never reaches any.
 */
export async function isStaffOnlyMember(): Promise<ApiResult<boolean>> {
  const result = await listMyOrganizations();
  if (!result.success) return result;
  return {
    success: true,
    data: result.data.length > 0 && pickBillingOrganization(result.data) === undefined,
  };
}

async function withManagedOrganization<T>(
  call: (organization: TeamOrganization) => Promise<ApiResult<T>>
): Promise<ApiResult<T>> {
  const organization = await resolveTeamOrganization();
  if (!organization.success) return organization;
  if (!organization.data) return { success: false, error: NO_TEAM_ORGANIZATION_MESSAGE };
  // The backend answers 403 too; checking here saves the calls for a STAFF member.
  if (!canManageTeam(organization.data.role)) {
    return { success: false, error: 'Forbidden', status: 403 };
  }
  return call(organization.data);
}

/** Members and pending invitations of the managed organisation (never a token or link). */
export function fetchTeam(): Promise<ApiResult<Team>> {
  return withManagedOrganization(async (organization) => {
    const path = { organization_id: organization.id };
    const [members, invitations] = await Promise.all([
      // Wrapped so callBackend keeps the whole page (it unwraps `{ success, data }` and would drop `total`).
      callBackend(async (client) => {
        const result = await listMembers({
          client,
          path,
          query: { limit: MEMBERS_PAGE_SIZE, offset: 0 },
        });
        return { ...result, data: result.data ? { page: result.data } : undefined };
      }),
      callBackend((client) => listInvitations({ client, path })),
    ]);
    if (!members.success) return members;
    if (!invitations.success) return invitations;
    return {
      success: true,
      data: {
        organization,
        members: members.data.page.data,
        membersTruncated: members.data.page.total > members.data.page.data.length,
        invitations: invitations.data,
      },
    };
  });
}

/** Creates an invitation; the response carries the accept link once (show it, never store or log it). */
export function createTeamInvitation(email: string, role: InviteRole) {
  return withManagedOrganization((organization) =>
    callBackend((client) =>
      createInvitation({
        client,
        path: { organization_id: organization.id },
        body: { email, role },
      })
    )
  );
}

/** Accepts an invitation for the signed-in user; the token goes in the POST body only. */
export function acceptTeamInvitation(token: string) {
  return callBackend((client) => acceptInvitation({ client, body: { token } }));
}
