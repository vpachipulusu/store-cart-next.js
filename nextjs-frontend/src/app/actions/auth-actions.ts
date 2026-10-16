'use server';

import { cookies, headers } from 'next/headers';
import { z } from 'zod';
import { auth } from '@/lib/firebase/client';
import { applyActionCode } from 'firebase/auth';
import { emailSchema, passwordSchema } from '@/lib/utils/validation';
import { logger } from '@/lib/logger';
import {
  isEmailNotVerifiedError,
  readSessionStatus,
  verifyVerifiedSessionCookie,
} from '@/lib/auth/verified-session';
import { SESSION_COOKIE_NAME } from '@/lib/api/server';
import { isSessionRejected } from '@/lib/api/session-rejected';
import {
  createBackendSession,
  fetchProfile,
  fetchSettings,
  refreshBackendSession,
  revokeBackendSession,
  toSettings,
  verifyBackendIdToken,
} from '@/lib/api/account';

/**
 * Response type for auth actions
 */
type AuthActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Login validation schema
 */
const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Password is required'),
});

/**
 * Signup validation schema
 */
const signUpSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  displayName: z.string().min(2, 'Display name must be at least 2 characters').optional(),
});

/**
 * Login action - validates credentials and sets session cookie
 */
export async function loginAction(email: string, password: string): Promise<AuthActionResponse> {
  try {
    // Validate input
    const validation = loginSchema.safeParse({ email, password });
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Note: Firebase client SDK handles the actual authentication
    // This server action is used for additional server-side operations
    return {
      success: true,
      data: { message: 'Login validation successful' },
    };
  } catch (error) {
    logger.error('Login action error:', error);
    return {
      success: false,
      error: 'Login failed',
    };
  }
}

/**
 * Signup action - creates user in Firebase and database
 */
export async function signUpAction(
  email: string,
  password: string,
  displayName?: string
): Promise<AuthActionResponse> {
  try {
    // Validate input
    const validation = signUpSchema.safeParse({ email, password, displayName });
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Note: Firebase client SDK creates the auth user
    // This action can be used for additional server-side setup
    return {
      success: true,
      data: { message: 'Signup validation successful' },
    };
  } catch (error) {
    logger.error('Signup action error:', error);
    return {
      success: false,
      error: 'Signup failed',
    };
  }
}

/**
 * Logout action - revokes the user's Firebase tokens through the API and clears the session cookie
 */
export async function logoutAction(): Promise<AuthActionResponse> {
  try {
    const cookieStore = await cookies();

    const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (sessionCookie) {
      // An expired or invalid session answers 401 here; the cookie is cleared either way.
      let revoked = await revokeBackendSession();
      // The backend rejecting the session (401) means there is nothing left to revoke. For an outage or server
      // error try once more, so a stolen cookie does not outlive the logout (there is no direct Firebase path).
      if (!revoked.success && revoked.status !== 401) {
        revoked = await revokeBackendSession();
      }
      if (!revoked.success) {
        logger.error('Token revocation during logout failed:', {
          status: revoked.status,
          error: revoked.error,
        });
      }
    }

    cookieStore.delete(SESSION_COOKIE_NAME);
    cookieStore.delete('email-verified');

    return {
      success: true,
      data: { message: 'Logged out successfully' },
    };
  } catch (error) {
    logger.error('Logout action error:', error);
    return {
      success: false,
      error: 'Logout failed',
    };
  }
}

/**
 * Explicit sign-in (login, signup, OAuth): verifies the token, syncs the user, mints the session
 * cookie and records ONE login-history row (plus the new-device notice).
 */
export async function verifyTokenAction(idToken: string): Promise<AuthActionResponse> {
  return establishSession(idToken, { isExplicitSignIn: true });
}

/**
 * Session refresh (Firebase token refresh, /verify-email re-check): same verification, user sync and
 * cookie as a sign-in, but records no login history and sends no new-device notice (KAN-163).
 * It only counts as a refresh when a current, unrevoked session cookie for the same uid exists;
 * otherwise it is treated as an explicit sign-in so a bare ID token can never mint a session silently.
 */
export async function refreshSessionAction(idToken: string): Promise<AuthActionResponse> {
  return establishSession(idToken, { isExplicitSignIn: false });
}

const GENERIC_SIGN_IN_ERROR = 'Token verification failed';
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 5; // 5 days, matches the backend session lifetime

/** Statuses meaning the API refused to refresh this session (as opposed to being down or rate limited). */
function isRefreshRejection(status: number | undefined): boolean {
  return status === 401 || status === 403 || status === 409 || status === 422;
}

async function hasMatchingActiveSession(uid: string): Promise<boolean> {
  const existing = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!existing) return false;
  try {
    // Revocation is checked by the backend; email_verified is deliberately not required (/verify-email
    // runs unverified).
    const claims = await readSessionStatus();
    return claims.uid === uid;
  } catch {
    return false;
  }
}

async function setSessionCookie(value: string, maxAgeSeconds: number): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE_NAME, value, {
    maxAge: maxAgeSeconds,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
  });
  // The email-verified decision lives in the signed claim inside the session cookie, enforced by
  // `@/lib/auth/verified-session` (KAN-123). No client-readable verification cookie is issued any more;
  // clear any left over from an older deployment.
  cookieStore.delete('email-verified');
}

async function establishSession(
  idToken: string,
  { isExplicitSignIn: requestedExplicit }: { isExplicitSignIn: boolean }
): Promise<AuthActionResponse> {
  try {
    // Verify Firebase ID token, rejecting revoked tokens (KAN-168). A revoked or invalid token gets the
    // generic failure only: no Firebase error detail reaches the client.
    const verified = await verifyBackendIdToken(idToken);
    if (!verified.success) {
      logger.error('ID token verification failed:', { status: verified.status, error: verified.error });
      return { success: false, error: GENERIC_SIGN_IN_ERROR };
    }
    const { uid, email, email_verified } = verified.data;
    const isExplicitSignIn = requestedExplicit || !(await hasMatchingActiveSession(uid));

    if (!email) {
      return {
        success: false,
        error: 'Email not found in token',
      };
    }

    // Explicit sign-in: the API verifies the token again (fresh sign-in required), syncs the platform user,
    // records ONE login-history row and returns the session cookie only after both commit.
    // Refresh: needs the current session and the same uid; the API records no login history (KAN-179).
    const session = isExplicitSignIn
      ? await createBackendSession(idToken, (await headers()).get('user-agent'))
      : await refreshBackendSession(idToken);
    if (!session.success) {
      logger.error(
        isExplicitSignIn ? 'Backend session creation failed:' : 'Backend session refresh failed:',
        { status: session.status, error: session.error }
      );
      if (!isExplicitSignIn && isRefreshRejection(session.status)) {
        // The API refused: the session is revoked or mismatched, or the ID token is too old to mint a
        // cookie. It cannot be extended, so drop it and make the user sign in again. Never a silent success.
        (await cookies()).delete(SESSION_COOKIE_NAME);
        return { success: false, error: GENERIC_SIGN_IN_ERROR, data: { signInRequired: true } };
      }
      // Outage, rate limit or server error: keep the current cookie; the next refresh retries.
      return { success: false, error: GENERIC_SIGN_IN_ERROR };
    }
    const maxAge = Number.isFinite(session.data.expires_in)
      ? Math.min(Math.max(Math.trunc(session.data.expires_in), 1), SESSION_MAX_AGE_SECONDS)
      : SESSION_MAX_AGE_SECONDS;
    await setSessionCookie(session.data.session_cookie, maxAge);

    return {
      success: true,
      data: {
        // From the verified ID token that minted the session cookie.
        claimsEmailVerified: email_verified === true,
      },
    };
  } catch (error: unknown) {
    logger.error('Verify token error:', error);
    return {
      success: false,
      error: GENERIC_SIGN_IN_ERROR,
    };
  }
}

/**
 * Get current session
 */
export async function getCurrentSessionAction(): Promise<AuthActionResponse> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;

    if (!sessionCookie) {
      return {
        success: false,
        error: 'No session found',
      };
    }

    // Verify session cookie (signature, revocation, verified email)
    const decodedClaims = await verifyVerifiedSessionCookie();

    const [profile, settings] = await Promise.all([fetchProfile(), fetchSettings()]);
    if (!profile.success || !settings.success) {
      const failed = profile.success ? settings : profile;
      if (!failed.success && isSessionRejected(failed)) {
        // Revoked or no platform user for this session: fall through to the cookie-clearing path.
        throw Object.assign(new Error('Session rejected by the backend'), {
          code: 'auth/invalid-session-cookie',
        });
      }
      // An outage or server error is not a reason to log the user out.
      logger.error('Get session backend request failed:', {
        status: failed.success ? undefined : failed.status,
      });
      return { success: false, error: 'Session retrieval failed' };
    }

    return {
      success: true,
      data: {
        user: {
          id: profile.data.id,
          firebaseUid: decodedClaims.uid,
          email: profile.data.email,
          emailVerified: profile.data.email_verified,
          displayName: profile.data.display_name,
          avatarUrl: profile.data.avatar_url,
          settings: toSettings(settings.data),
        },
      },
    };
  } catch (error: unknown) {
    logger.error('Get session error:', error);
    // Clear stale cookie on verification failure. An unverified user keeps the session so they can
    // finish verifying their email.
    if (!isEmailNotVerifiedError(error)) {
      const cookieStore = await cookies();
      cookieStore.delete(SESSION_COOKIE_NAME);
      cookieStore.delete('email-verified');
    }
    return {
      success: false,
      error: 'Session retrieval failed',
    };
  }
}

/**
 * Verify email action
 */
export async function verifyEmailAction(oobCode: string): Promise<AuthActionResponse> {
  try {
    // Apply email verification code
    await applyActionCode(auth, oobCode);

    return {
      success: true,
      data: { message: 'Email verified successfully' },
    };
  } catch (error) {
    logger.error('Email verification error:', error);
    return {
      success: false,
      error: 'Email verification failed',
    };
  }
}
