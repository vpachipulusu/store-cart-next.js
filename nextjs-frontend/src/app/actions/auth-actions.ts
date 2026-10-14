'use server';

import { cookies, headers } from 'next/headers';
import { z } from 'zod';
import { getAdminAuth } from '@/lib/firebase/admin';
import { auth } from '@/lib/firebase/client';
import { applyActionCode } from 'firebase/auth';
import { emailSchema, passwordSchema } from '@/lib/utils/validation';
import { logger } from '@/lib/logger';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';
import { SESSION_COOKIE_NAME } from '@/lib/api/server';
import {
  createBackendSession,
  fetchProfile,
  fetchSettings,
  revokeBackendSession,
  toSettings,
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

    if (cookieStore.get(SESSION_COOKIE_NAME)?.value) {
      // An expired or invalid session answers 401 here; the cookie is cleared either way.
      const revoked = await revokeBackendSession();
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

async function hasMatchingActiveSession(uid: string): Promise<boolean> {
  const existing = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!existing) return false;
  try {
    // checkRevoked = true; email_verified is deliberately not required (/verify-email runs unverified).
    const claims = await getAdminAuth().verifySessionCookie(existing, true);
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
    let decodedToken;
    try {
      decodedToken = await getAdminAuth().verifyIdToken(idToken, true);
    } catch (verifyError) {
      logger.error('ID token verification failed:', verifyError);
      return { success: false, error: GENERIC_SIGN_IN_ERROR };
    }
    const { uid, email, email_verified } = decodedToken;
    const isExplicitSignIn = requestedExplicit || !(await hasMatchingActiveSession(uid));

    if (!email) {
      return {
        success: false,
        error: 'Email not found in token',
      };
    }

    if (isExplicitSignIn) {
      // The API verifies the token again (fresh sign-in required), syncs the platform user, records ONE
      // login-history row and returns the session cookie only after both commit.
      const userAgent = (await headers()).get('user-agent');
      const session = await createBackendSession(idToken, userAgent);
      if (!session.success) {
        logger.error('Backend session creation failed:', {
          status: session.status,
          error: session.error,
        });
        return { success: false, error: GENERIC_SIGN_IN_ERROR };
      }
      await setSessionCookie(session.data.session_cookie, session.data.expires_in);
    } else {
      // TODO(KAN-179): move to POST /v1/auth/session/refresh. Until it exists the API cannot mint a cookie
      // from an aged ID token without a fresh sign-in and a login-history row, so a refresh only re-mints the
      // Firebase session cookie and does not sync email_verified to the platform user (it syncs at next sign-in).
      const sessionCookie = await getAdminAuth().createSessionCookie(idToken, {
        expiresIn: SESSION_MAX_AGE_SECONDS * 1000,
      });
      await setSessionCookie(sessionCookie, SESSION_MAX_AGE_SECONDS);
    }

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
    const decodedClaims = await verifyVerifiedSessionCookie(sessionCookie);

    const [profile, settings] = await Promise.all([fetchProfile(), fetchSettings()]);
    if (!profile.success || !settings.success) {
      const failed = profile.success ? settings : profile;
      if (!failed.success && failed.status === 404) {
        return { success: false, error: 'User not found' };
      }
      throw new Error('Backend profile request failed');
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
