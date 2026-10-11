/**
 * Signup API Route Handler
 *
 * Handles new user registration with Firebase authentication
 */

import { NextRequest, NextResponse } from 'next/server';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { z } from 'zod';
import { logger } from '@/lib/logger';

const signupSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  displayName: z.string().min(2, 'Display name must be at least 2 characters').optional(),
});

/**
 * POST /api/auth/signup
 *
 * Create new Firebase user and database record
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Validate request body
    const validation = signupSchema.safeParse(body);
    if (!validation.success) {
      return NextResponse.json(
        { error: 'Invalid request', details: validation.error.errors },
        { status: 400 }
      );
    }

    const { email, password, displayName } = validation.data;

    // Check if user already exists in database
    const existingUser = await db.user.findUnique({
      where: { email },
    });

    if (existingUser) {
      return NextResponse.json({ error: 'User with this email already exists' }, { status: 409 });
    }

    // Create Firebase user
    let firebaseUser;
    try {
      firebaseUser = await adminAuth.createUser({
        email,
        password,
        displayName: displayName || undefined,
        emailVerified: false,
      });
    } catch (error: any) {
      logger.error('Firebase user creation failed:', error);

      // Handle specific Firebase errors
      if (error.code === 'auth/email-already-exists') {
        return NextResponse.json(
          { error: 'Email already registered in authentication system' },
          { status: 409 }
        );
      }

      if (error.code === 'auth/invalid-password') {
        return NextResponse.json({ error: 'Password does not meet requirements' }, { status: 400 });
      }

      return NextResponse.json({ error: 'Failed to create user account' }, { status: 500 });
    }

    // Get client IP and user agent
    const forwardedFor = request.headers.get('x-forwarded-for');
    const ipAddress = forwardedFor ? forwardedFor.split(',')[0].trim() : null;
    const userAgent = request.headers.get('user-agent');

    // Create user in database
    try {
      const newUser = await db.user.create({
        data: {
          firebaseUid: firebaseUser.uid,
          email,
          emailVerified: false,
          displayName: displayName || null,
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
        },
      });

      // Create audit log
      await db.auditLog.create({
        data: {
          userId: newUser.id,
          action: 'user.signup',
          resource: 'User',
          resourceId: newUser.id,
          ipAddress,
          userAgent,
          metadata: {
            email,
            displayName: displayName || null,
          },
        },
      });

      // Create welcome notification
      await db.notification.create({
        data: {
          userId: newUser.id,
          type: 'welcome',
          title: 'Welcome!',
          message: `Welcome to ${process.env.NEXT_PUBLIC_APP_NAME || 'our platform'}! Get started by exploring your dashboard.`,
          link: '/dashboard',
        },
      });

      // Generate custom token for immediate login
      const customToken = await adminAuth.createCustomToken(firebaseUser.uid);

      return NextResponse.json(
        {
          success: true,
          message: 'Account created successfully',
          user: {
            id: newUser.id,
            email: newUser.email,
            displayName: newUser.displayName,
            emailVerified: newUser.emailVerified,
          },
          customToken, // Client can use this to sign in immediately
        },
        { status: 201 }
      );
    } catch (dbError) {
      logger.error('Database user creation failed:', dbError);

      // Cleanup: Delete Firebase user if database creation fails
      try {
        await adminAuth.deleteUser(firebaseUser.uid);
        logger.info(`Cleaned up Firebase user: ${firebaseUser.uid}`);
      } catch (cleanupError) {
        logger.error('Failed to cleanup Firebase user:', cleanupError);
      }

      return NextResponse.json({ error: 'Failed to create user account' }, { status: 500 });
    }
  } catch (error) {
    logger.error('Signup error:', error);

    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

/**
 * OPTIONS /api/auth/signup
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
