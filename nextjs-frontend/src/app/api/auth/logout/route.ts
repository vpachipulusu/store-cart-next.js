/**
 * Logout API Route Handler
 *
 * Handles user logout and session cleanup
 */

import { NextRequest, NextResponse } from 'next/server';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * POST /api/auth/logout
 *
 * Clear user session and revoke tokens
 */
export async function POST(request: NextRequest) {
  try {
    // Get token from cookie or header
    const cookieToken = request.cookies.get('session');
    const authHeader = request.headers.get('authorization');
    const headerToken = authHeader?.startsWith('Bearer ') ? authHeader.substring(7) : null;

    const sessionCookie = cookieToken?.value;

    if (!sessionCookie && !headerToken) {
      // No token to logout, but still clear cookie
      const response = NextResponse.json(
        { success: true, message: 'Logged out successfully' },
        { status: 200 }
      );

      response.cookies.delete('session');
      response.cookies.delete('email-verified');
      return response;
    }

    // Verify token to get user info
    // Session cookies use verifySessionCookie, Bearer tokens use verifyIdToken
    let firebaseUid: string;
    try {
      if (headerToken) {
        const decoded = await adminAuth.verifyIdToken(headerToken);
        firebaseUid = decoded.uid;
      } else {
        const decoded = await adminAuth.verifySessionCookie(sessionCookie!, false);
        firebaseUid = decoded.uid;
      }
    } catch (error) {
      logger.error('Token verification failed during logout:', error);
      // Token invalid/expired, but still clear cookie
      const response = NextResponse.json(
        { success: true, message: 'Logged out successfully' },
        { status: 200 }
      );

      response.cookies.delete('session');
      response.cookies.delete('email-verified');
      return response;
    }

    // Revoke all refresh tokens for this user
    try {
      await adminAuth.revokeRefreshTokens(firebaseUid);
      logger.info(`Revoked tokens for user: ${firebaseUid}`);
    } catch (error) {
      logger.error('Error revoking tokens:', error);
      // Continue with logout even if revocation fails
    }

    // Find user in database
    const user = await db.user.findUnique({
      where: { firebaseUid },
    });

    if (user) {
      // Create audit log
      const forwardedFor = request.headers.get('x-forwarded-for');
      const ipAddress = forwardedFor ? forwardedFor.split(',')[0].trim() : null;

      await db.auditLog.create({
        data: {
          userId: user.id,
          action: 'user.logout',
          resource: 'User',
          resourceId: user.id,
          ipAddress,
          userAgent: request.headers.get('user-agent'),
        },
      });
    }

    // Create response and clear cookie
    const response = NextResponse.json(
      { success: true, message: 'Logged out successfully' },
      { status: 200 }
    );

    response.cookies.delete('session');
    response.cookies.delete('email-verified');

    return response;
  } catch (error) {
    logger.error('Logout error:', error);

    // Even on error, clear the cookie
    const response = NextResponse.json(
      { error: 'Logout failed, but session cleared' },
      { status: 500 }
    );

    response.cookies.delete('session');
    response.cookies.delete('email-verified');

    return response;
  }
}

/**
 * OPTIONS /api/auth/logout
 *
 * Handle CORS preflight
 */
export async function OPTIONS() {
  return new NextResponse(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}
