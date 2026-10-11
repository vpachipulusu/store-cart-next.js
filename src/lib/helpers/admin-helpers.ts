'use server';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

export interface AdminUser {
  id: string;
  email: string;
  displayName: string | null;
  role: string;
  permissions: string[];
}

/**
 * Require admin authentication and authorization
 * Throws error or redirects if not authorized
 */
export async function requireAdmin(): Promise<AdminUser> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      redirect('/login');
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);

    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        adminUser: true,
      },
    });

    if (!user || !user.adminUser) {
      redirect('/dashboard');
    }

    return {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      role: user.adminUser.role,
      permissions: user.adminUser.permissions as string[],
    };
  } catch (error) {
    logger.error('Admin auth error:', error);
    redirect('/login');
  }
}

/**
 * Check if admin has a specific permission
 */
export function hasPermission(admin: AdminUser, permission: string): boolean {
  return admin.permissions.includes('*') || admin.permissions.includes(permission);
}

/**
 * Require a specific permission
 * Throws error if permission not granted
 */
export async function requirePermission(permission: string): Promise<AdminUser> {
  const admin = await requireAdmin();

  if (!hasPermission(admin, permission)) {
    throw new Error(`Permission denied: ${permission}`);
  }

  return admin;
}

/**
 * Check if user is admin (without redirecting)
 */
export async function isAdmin(): Promise<boolean> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return false;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);

    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        adminUser: true,
      },
    });

    return !!(user && user.adminUser);
  } catch (error) {
    return false;
  }
}

/**
 * Get current admin user (without redirecting)
 */
export async function getCurrentAdmin(): Promise<AdminUser | null> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);

    const user = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      include: {
        adminUser: true,
      },
    });

    if (!user || !user.adminUser) {
      return null;
    }

    return {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      role: user.adminUser.role,
      permissions: user.adminUser.permissions as string[],
    };
  } catch (error) {
    logger.error('Get current admin error:', error);
    return null;
  }
}
