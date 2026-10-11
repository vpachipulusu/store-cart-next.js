/**
 * Login API Route Handler
 *
 * Handles user login with Firebase authentication
 */

import { NextRequest, NextResponse } from 'next/server';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { z } from 'zod';
import { logger } from '@/lib/logger';

const loginSchema = z.object({
  idToken: z.string().min(1, 'ID token is required'),
});

/**
 * POST /api/auth/login
 *
 * Verify Firebase ID token and create/update user session
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Validate request body
    const validation = loginSchema.safeParse(body);
    if (!validation.success) {
      return NextResponse.json(
        { error: 'Invalid request', details: validation.error.errors },
        { status: 400 }
      );
    }

    const { idToken } = validation.data;

    // Verify Firebase ID token
    let decodedToken;
    try {
      decodedToken = await adminAuth.verifyIdToken(idToken);
    } catch (error) {
      logger.error('Token verification failed:', error);
      return NextResponse.json({ error: 'Invalid or expired token' }, { status: 401 });
    }

    const { uid: firebaseUid, email, email_verified } = decodedToken;

    if (!email) {
      return NextResponse.json({ error: 'Email not found in token' }, { status: 400 });
    }

    // Get client IP and user agent
    const forwardedFor = request.headers.get('x-forwarded-for');
    const ipAddress = forwardedFor ? forwardedFor.split(',')[0].trim() : null;
    const userAgent = request.headers.get('user-agent');

    // Find or create user in database
    let user = await db.user.findUnique({
      where: { firebaseUid },
      include: {
        settings: true,
        adminUser: true,
      },
    });

    if (!user) {
      // Create new user
      user = await db.user.create({
        data: {
          firebaseUid,
          email,
          emailVerified: email_verified || false,
          lastLoginAt: new Date(),
          settings: {
            create: {
              theme: 'system',
              emailNotifications: true,
              language: 'en',
              timezone: 'UTC',
            },
          },
        },
        include: {
          settings: true,
          adminUser: true,
        },
      });

      // Create audit log for new user
      await db.auditLog.create({
        data: {
          userId: user.id,
          action: 'user.created',
          resource: 'User',
          resourceId: user.id,
          ipAddress,
          userAgent,
        },
      });

      logger.info(`New user created: ${user.id}`);
    } else {
      // Update last login time
      user = await db.user.update({
        where: { id: user.id },
        data: {
          lastLoginAt: new Date(),
          emailVerified: email_verified || user.emailVerified,
        },
        include: {
          settings: true,
          adminUser: true,
        },
      });
    }

    // Create login history record
    await db.loginHistory.create({
      data: {
        userId: user.id,
        ipAddress,
        userAgent,
        successful: true,
      },
    });

    // Create session token cookie
    const response = NextResponse.json(
      {
        success: true,
        user: {
          id: user.id,
          email: user.email,
          emailVerified: user.emailVerified,
          displayName: user.displayName,
          avatarUrl: user.avatarUrl,
          subscriptionTier: user.subscriptionTier,
          subscriptionStatus: user.subscriptionStatus,
          isAdmin: !!user.adminUser,
        },
      },
      { status: 200 }
    );

    // Set HTTP-only cookie with the ID token
    response.cookies.set('auth-token', idToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: '/',
    });

    return response;
  } catch (error) {
    logger.error('Login error:', error);

    // Log failed login attempt if we have enough info
    try {
      const body = await request.clone().json();
      if (body.idToken) {
        const forwardedFor = request.headers.get('x-forwarded-for');
        const ipAddress = forwardedFor ? forwardedFor.split(',')[0].trim() : null;

        await db.auditLog.create({
          data: {
            action: 'user.login_failed',
            resource: 'User',
            ipAddress,
            userAgent: request.headers.get('user-agent'),
            metadata: { error: error instanceof Error ? error.message : 'Unknown error' },
          },
        });
      }
    } catch {
      // Ignore errors in error logging
    }

    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

/**
 * OPTIONS /api/auth/login
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
