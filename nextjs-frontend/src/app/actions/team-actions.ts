'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { logger } from '@/lib/logger';
import { getVerifiedUserId } from '@/lib/auth/verified-session';
import {
  NO_TEAM_ORGANIZATION_MESSAGE,
  acceptTeamInvitation,
  createTeamInvitation,
  type InviteRole,
} from '@/lib/api/team';

/**
 * Team invitation server actions (KAN-62). Input is validated with Zod; the organisation is resolved on the server
 * (never taken from the browser) and the backend authorises the call again. Messages shown to the browser are
 * curated here; the accept link and token are never logged.
 */

type ActionFailure = { success: false; error: string };
type ActionResponse<T> = { success: true; data: T } | ActionFailure;

/** `wrong_account`: signed in with an address the invitation was not sent to (the page offers a sign-out). */
export type AcceptFailureKind = 'wrong_account' | 'other';
type AcceptResponse =
  | { success: true; data: { role: string } }
  | (ActionFailure & { kind: AcceptFailureKind });

const MESSAGES = {
  session: 'Your session has expired. Please sign in again.',
  invalidEmail: 'Enter a valid email address.',
  invalidRole: 'Choose Admin or Staff.',
  noOrganization: 'Create a store first. Your team belongs to your store’s organisation.',
  forbidden: 'Only an organisation owner or admin can manage the team.',
  notFound: 'We could not find this organisation.',
  notConfigured: 'Invitations are not available right now. Please try again later.',
  inviteFailed: 'We could not send the invitation. Please try again.',
  invalidLink: 'This invitation link is not valid.',
  linkExpired: 'This invitation is invalid, has already been used or has expired.',
  wrongEmail:
    'This invitation was sent to a different email address. Sign in with that address to accept it.',
  acceptFailed: 'We could not accept the invitation. Please try again.',
} as const;

/** Backend 409 messages shown as they are; anything else gets the generic message. */
const ALREADY_MEMBER = 'Already a member of this organization';
const SAFE_CONFLICTS: ReadonlyArray<string | RegExp> = [
  ALREADY_MEMBER,
  'Too many pending invitations',
  /^The [A-Za-z]+ plan allows \d+ team members?\. Upgrade your plan to add more\.$/,
];

function safeConflict(error: string, fallback: string): string {
  const known = SAFE_CONFLICTS.some((pattern) =>
    typeof pattern === 'string' ? pattern === error : pattern.test(error)
  );
  return known ? error : fallback;
}

const ROLES = ['ADMIN', 'STAFF'] as const satisfies ReadonlyArray<InviteRole>;

const inviteSchema = z.object(
  {
    email: z
      .string({ error: MESSAGES.invalidEmail })
      .trim()
      .max(254, { error: MESSAGES.invalidEmail })
      .pipe(z.email({ error: MESSAGES.invalidEmail })),
    role: z.enum(ROLES, { error: MESSAGES.invalidRole }),
  },
  { error: MESSAGES.invalidEmail }
);

const tokenSchema = z
  .string({ error: MESSAGES.invalidLink })
  .regex(/^[A-Za-z0-9_-]{16,128}$/, { error: MESSAGES.invalidLink });

export type InviteResult = { email: string; acceptUrl: string; emailSent: boolean };

function errorClass(error: unknown): string {
  return error instanceof Error ? error.constructor.name : typeof error;
}

function inviteFailure(error: string, status: number | undefined): string {
  if (error === NO_TEAM_ORGANIZATION_MESSAGE) return MESSAGES.noOrganization;
  switch (status) {
    case 401:
      return MESSAGES.session;
    case 403:
      return MESSAGES.forbidden;
    case 404:
      return MESSAGES.notFound;
    case 409:
      return safeConflict(error, MESSAGES.inviteFailed);
    case 422:
      return MESSAGES.invalidEmail;
    case 503:
      return MESSAGES.notConfigured;
    default:
      return MESSAGES.inviteFailed;
  }
}

function acceptFailure(error: string, status: number | undefined): string {
  switch (status) {
    case 401:
      return MESSAGES.session;
    case 403:
      return MESSAGES.wrongEmail;
    case 409:
      return safeConflict(error, MESSAGES.acceptFailed);
    case 410:
      return MESSAGES.linkExpired;
    case 422:
      return MESSAGES.invalidLink;
    default:
      return MESSAGES.acceptFailed;
  }
}

export async function inviteTeamMemberAction(
  input: unknown
): Promise<ActionResponse<InviteResult>> {
  const parsed = inviteSchema.safeParse(input);
  if (!parsed.success) {
    return { success: false, error: parsed.error.issues[0]?.message ?? MESSAGES.invalidEmail };
  }
  try {
    if (!(await getVerifiedUserId())) return { success: false, error: MESSAGES.session };

    const result = await createTeamInvitation(parsed.data.email, parsed.data.role);
    if (!result.success) {
      logger.warn('Create invitation failed:', { status: result.status });
      return { success: false, error: inviteFailure(result.error, result.status) };
    }
    revalidatePath('/dashboard/settings/team');
    return {
      success: true,
      data: {
        email: result.data.email,
        acceptUrl: result.data.accept_url,
        emailSent: result.data.email_sent,
      },
    };
  } catch (error: unknown) {
    logger.error('Create invitation error:', { cause: errorClass(error) });
    return { success: false, error: MESSAGES.inviteFailed };
  }
}

export async function acceptInvitationAction(token: unknown): Promise<AcceptResponse> {
  const parsed = tokenSchema.safeParse(token);
  if (!parsed.success) return { success: false, error: MESSAGES.invalidLink, kind: 'other' };
  try {
    if (!(await getVerifiedUserId())) {
      return { success: false, error: MESSAGES.session, kind: 'other' };
    }

    const result = await acceptTeamInvitation(parsed.data);
    if (!result.success) {
      logger.warn('Accept invitation failed:', { status: result.status });
      return {
        success: false,
        error: acceptFailure(result.error, result.status),
        kind: result.status === 403 ? 'wrong_account' : 'other',
      };
    }
    revalidatePath('/dashboard', 'layout');
    return { success: true, data: { role: result.data.role } };
  } catch (error: unknown) {
    logger.error('Accept invitation error:', { cause: errorClass(error) });
    return { success: false, error: MESSAGES.acceptFailed, kind: 'other' };
  }
}
