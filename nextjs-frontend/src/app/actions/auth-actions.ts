'use server';

import { cookies, headers } from 'next/headers';
import { z } from 'zod';
import { getAdminAuth } from '@/lib/firebase/admin';
import { auth } from '@/lib/firebase/client';
import { applyActionCode } from 'firebase/auth';
import { db } from '@/lib/db/client';
import { emailSchema, passwordSchema } from '@/lib/utils/validation';
import { getLocationFromIP } from '@/lib/utils/geo-ip';
import { notifyNewDeviceLogin, notifyEmailVerified } from '@/lib/utils/notifications';
import { logger } from '@/lib/logger';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';

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
  } catch (error: any) {
    logger.error('Login action error:', error);
    return {
      success: false,
      error: error.message || 'Login failed',
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
  } catch (error: any) {
    logger.error('Signup action error:', error);
    return {
      success: false,
      error: error.message || 'Signup failed',
    };
  }
}

/**
 * Logout action - revokes Firebase tokens and clears session cookie
 */
export async function logoutAction(): Promise<AuthActionResponse> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (sessionCookie) {
      try {
        // Verify session to get Firebase UID (don't check revocation)
        const decodedClaims = await getAdminAuth().verifySessionCookie(sessionCookie, false);
        // Revoke all refresh tokens for this user
        await getAdminAuth().revokeRefreshTokens(decodedClaims.uid);
      } catch (error) {
        // Session may be expired/invalid, still proceed with cookie deletion
        logger.error('Token revocation during logout failed:', error);
      }
    }

    cookieStore.delete('session');
    cookieStore.delete('email-verified');

    return {
      success: true,
      data: { message: 'Logged out successfully' },
    };
  } catch (error: any) {
    logger.error('Logout action error:', error);
    return {
      success: false,
      error: error.message || 'Logout failed',
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
 */
export async function refreshSessionAction(idToken: string): Promise<AuthActionResponse> {
  return establishSession(idToken, { isExplicitSignIn: false });
}

async function establishSession(
  idToken: string,
  { isExplicitSignIn }: { isExplicitSignIn: boolean }
): Promise<AuthActionResponse> {
  try {
    // Verify Firebase ID token
    const decodedToken = await getAdminAuth().verifyIdToken(idToken);
    const { uid, email, email_verified } = decodedToken;

    if (!email) {
      return {
        success: false,
        error: 'Email not found in token',
      };
    }

    // Get full Firebase user data to access displayName
    const firebaseUser = await getAdminAuth().getUser(uid);

    // Get request headers for login tracking
    const headersList = await headers();
    const ipAddress =
      headersList.get('x-forwarded-for')?.split(',')[0].trim() ||
      headersList.get('x-real-ip') ||
      'unknown';
    const userAgent = headersList.get('user-agent') || 'unknown';

    // Get or create user in database
    let user = await db.user.findUnique({
      where: { firebaseUid: uid },
      include: {
        settings: true,
        adminUser: true,
      },
    });

    if (!user) {
      // Every new account starts on free. The client's selected plan is never trusted for the tier:
      // paid tiers are granted only by Stripe checkout (KAN-122).
      const subscriptionTier = 'free';

      // Create new user in database
      user = await db.user.create({
        data: {
          firebaseUid: uid,
          email,
          emailVerified: email_verified || false,
          displayName: firebaseUser.displayName || null,
          avatarUrl: firebaseUser.photoURL || null,
          phoneNumber: firebaseUser.phoneNumber || null,
          lastLoginAt: new Date(),
          subscriptionTier,
        },
        include: {
          settings: true,
          adminUser: true,
        },
      });

      // Create default settings
      await db.userSettings.create({
        data: {
          userId: user.id,
        },
      });
    } else {
      // Notify if email was just verified
      if (email_verified && !user.emailVerified) {
        await notifyEmailVerified(user.id);
      }

      // Update last login (explicit sign-ins only) and sync displayName/avatar from Firebase
      await db.user.update({
        where: { id: user.id },
        data: {
          ...(isExplicitSignIn ? { lastLoginAt: new Date() } : {}),
          emailVerified: email_verified || user.emailVerified,
          displayName: firebaseUser.displayName || user.displayName,
          avatarUrl: firebaseUser.photoURL || user.avatarUrl,
        },
      });
    }

    if (isExplicitSignIn) {
      // Get location from IP address
      const location = await getLocationFromIP(ipAddress);

      // Check if this is a new device (no previous login with same userAgent)
      if (userAgent) {
        const previousLogin = await db.loginHistory.findFirst({
          where: { userId: user.id, userAgent },
        });
        if (!previousLogin) {
          await notifyNewDeviceLogin(user.id, ipAddress);
        }
      }

      // Record login history
      await db.loginHistory.create({
        data: {
          userId: user.id,
          ipAddress,
          userAgent,
          location,
          successful: true,
          loginAt: new Date(),
        },
      });
    }

    // Set session cookie
    const expiresIn = 60 * 60 * 24 * 5 * 1000; // 5 days in ms (for Firebase)
    const maxAgeSeconds = 60 * 60 * 24 * 5; // 5 days in seconds (for cookie maxAge)
    const sessionCookie = await getAdminAuth().createSessionCookie(idToken, { expiresIn });

    const cookieStore = await cookies();
    cookieStore.set('session', sessionCookie, {
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

    return {
      success: true,
      data: {
        // From the verified ID token that minted the session cookie (not the database row).
        claimsEmailVerified: email_verified === true,
        user: {
          id: user.id,
          firebaseUid: user.firebaseUid,
          email: user.email,
          emailVerified: user.emailVerified,
          displayName: user.displayName,
          avatarUrl: user.avatarUrl,
          subscriptionTier: user.subscriptionTier,
          subscriptionStatus: user.subscriptionStatus,
          isAdmin: !!user.adminUser,
        },
      },
    };
  } catch (error: any) {
    logger.error('Verify token error:', error);
    return {
      success: false,
      error: error.message || 'Token verification failed',
    };
  }
}

/**
 * Get current session
 */
export async function getCurrentSessionAction(): Promise<AuthActionResponse> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return {
        success: false,
        error: 'No session found',
      };
    }

    // Verify session cookie
    const decodedClaims = await verifyVerifiedSessionCookie(sessionCookie);

    // Get user from database
    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        settings: true,
        adminUser: true,
      },
    });

    if (!user) {
      return {
        success: false,
        error: 'User not found',
      };
    }

    return {
      success: true,
      data: {
        user: {
          id: user.id,
          firebaseUid: user.firebaseUid,
          email: user.email,
          emailVerified: user.emailVerified,
          displayName: user.displayName,
          avatarUrl: user.avatarUrl,
          subscriptionTier: user.subscriptionTier,
          subscriptionStatus: user.subscriptionStatus,
          isAdmin: !!user.adminUser,
          settings: user.settings,
        },
      },
    };
  } catch (error: any) {
    logger.error('Get session error:', error);
    // Clear stale cookie on verification failure. An unverified user keeps the session so they can
    // finish verifying their email.
    if (!isEmailNotVerifiedError(error)) {
      const cookieStore = await cookies();
      cookieStore.delete('session');
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
  } catch (error: any) {
    logger.error('Email verification error:', error);
    return {
      success: false,
      error: error.message || 'Email verification failed',
    };
  }
}
