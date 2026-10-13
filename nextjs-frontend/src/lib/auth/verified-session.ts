import { cookies } from 'next/headers';
import type { DecodedIdToken } from 'firebase-admin/auth';
import { getAdminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * The legacy (Next.js server) authorization boundary for KAN-123.
 *
 * Authorization is decided only from the httpOnly `session` cookie, verified by firebase-admin with
 * revocation checking, and the signed `email_verified` claim inside it. The client-writable
 * `email-verified` cookie is never read here, so a forged, stale or missing cookie cannot authorize
 * (or block) anyone. The proxy runs at the edge and cannot verify Firebase tokens, so every server page,
 * server action and API route that serves protected data must call this module.
 */

export const EMAIL_NOT_VERIFIED_CODE = 'auth/email-not-verified';

export class EmailNotVerifiedError extends Error {
  readonly code = EMAIL_NOT_VERIFIED_CODE;

  constructor() {
    super('Email address is not verified');
    this.name = 'EmailNotVerifiedError';
  }
}

export function isEmailNotVerifiedError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { code?: unknown }).code === EMAIL_NOT_VERIFIED_CODE
  );
}

/**
 * Verifies a session cookie (signature, expiry and revocation) and requires the verified-email claim.
 * Rejects with a firebase-admin error for an invalid, expired or revoked session, or with
 * `EmailNotVerifiedError` when the session belongs to an unverified user.
 */
export async function verifyVerifiedSessionCookie(sessionCookie: string): Promise<DecodedIdToken> {
  const claims = await getAdminAuth().verifySessionCookie(sessionCookie, true);
  if (claims.email_verified !== true) {
    throw new EmailNotVerifiedError();
  }
  return claims;
}

/**
 * Verified claims for the current request, or null when there is no session cookie.
 * Rejects like `verifyVerifiedSessionCookie` for a bad or unverified session.
 */
export async function getVerifiedSessionClaims(): Promise<DecodedIdToken | null> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session')?.value;
  if (!sessionCookie) {
    return null;
  }
  return verifyVerifiedSessionCookie(sessionCookie);
}

/**
 * Database user id of the verified, signed-in user, or null for any failure (no session, invalid,
 * revoked, unverified, unknown user). For server actions that answer "Unauthorized".
 */
export async function getVerifiedUserId(): Promise<string | null> {
  try {
    const claims = await getVerifiedSessionClaims();
    if (!claims) {
      return null;
    }
    const user = await db.user.findUnique({
      where: { firebaseUid: claims.uid },
      select: { id: true },
    });
    return user?.id || null;
  } catch (error) {
    if (isEmailNotVerifiedError(error)) {
      logger.warn('Rejected request from a user with an unverified email');
    } else {
      logger.error('Authentication error:', error);
    }
    return null;
  }
}
