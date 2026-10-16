import { cookies } from 'next/headers';
import { fetchProfile, fetchSessionStatus } from '@/lib/api/account';
import { SESSION_COOKIE_NAME } from '@/lib/api/server';
import { INVALID_AUTHENTICATION_MESSAGE } from '@/lib/api/session-rejected';
import { logger } from '@/lib/logger';

/**
 * The legacy (Next.js server) authorization boundary for KAN-123.
 *
 * Authorization is decided only from the httpOnly `session` cookie, verified by the backend
 * (`GET /v1/auth/session/status`, KAN-208) with revocation checking, and the signed `email_verified` claim
 * inside it. The client-writable `email-verified` cookie is never read here, so a forged, stale or missing
 * cookie cannot authorize (or block) anyone. The proxy runs at the edge and cannot verify Firebase tokens, so
 * every server page, server action and API route that serves protected data must call this module.
 */

/** Identity of a verified session, as the backend reports it. */
export interface SessionClaims {
  uid: string;
  email: string;
  email_verified: boolean;
}

/** Code carried by the error thrown for a missing, invalid or revoked session (see `isSessionVerificationError`). */
export const INVALID_SESSION_CODE = 'auth/invalid-session-cookie';
const SESSION_CHECK_FAILED_MESSAGE = 'Session status check failed';

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
 * Verifies the current request's session cookie (signature, expiry and revocation, by the backend) and
 * requires the verified-email claim. Rejects with an `auth/invalid-session-cookie` error for a missing, invalid
 * or revoked session, with `EmailNotVerifiedError` for an unverified user, and with a plain error when the
 * backend or Firebase is unreachable (which must not log the user out).
 */
export async function verifyVerifiedSessionCookie(): Promise<SessionClaims> {
  const claims = await readSessionStatus();
  if (claims.email_verified !== true) {
    throw new EmailNotVerifiedError();
  }
  return claims;
}

/**
 * Identity of the current session with revocation checked. Unlike
 * `verifyVerifiedSessionCookie` an unverified email is allowed: callers read `email_verified` themselves.
 */
export async function readSessionStatus(): Promise<SessionClaims> {
  const status = await fetchSessionStatus();
  if (!status.success) {
    if (status.status === 401 && status.error === INVALID_AUTHENTICATION_MESSAGE) {
      throw Object.assign(new Error('Invalid session'), { code: INVALID_SESSION_CODE });
    }
    throw new Error(SESSION_CHECK_FAILED_MESSAGE);
  }
  return status.data;
}

/**
 * Verified claims for the current request, or null when there is no session cookie.
 * Rejects like `verifyVerifiedSessionCookie` for a bad or unverified session.
 */
export async function getVerifiedSessionClaims(): Promise<SessionClaims | null> {
  const cookieStore = await cookies();
  if (!cookieStore.get(SESSION_COOKIE_NAME)?.value) {
    return null;
  }
  return verifyVerifiedSessionCookie();
}

/**
 * Backend user id of the verified, signed-in user, or null for any failure (no session, invalid,
 * revoked, unverified, unknown user, backend failure). For server actions that answer "Unauthorized".
 */
export async function getVerifiedUserId(): Promise<string | null> {
  try {
    const claims = await getVerifiedSessionClaims();
    if (!claims) {
      return null;
    }
    // GET /v1/me with the same session cookie; the backend id is authoritative.
    const profile = await fetchProfile();
    if (!profile.success) {
      logger.error('Authentication error: backend profile lookup failed', {
        status: profile.status,
        error: profile.error,
      });
      return null;
    }
    return typeof profile.data.id === 'string' && profile.data.id ? profile.data.id : null;
  } catch (error) {
    if (isEmailNotVerifiedError(error)) {
      logger.warn('Rejected request from a user with an unverified email');
    } else {
      logger.error('Authentication error:', error);
    }
    return null;
  }
}
