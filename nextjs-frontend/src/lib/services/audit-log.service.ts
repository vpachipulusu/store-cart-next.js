'use server';

import { db } from '@/lib/db/client';
import { cookies } from 'next/headers';
import { adminAuth } from '@/lib/firebase/admin';
import { logger } from '@/lib/logger';

export interface LogAuditParams {
  action: string;
  resource: string;
  resourceId?: string;
  metadata?: any;
  ipAddress?: string;
  userAgent?: string;
}

/**
 * Log an admin action to the audit log
 */
export async function logAdminAction(params: LogAuditParams) {
  try {
    // Get current admin user
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    let userId: string | undefined;

    if (sessionCookie) {
      try {
        const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);
        const user = await db.user.findUnique({
          where: { firebaseUid: decodedClaims.uid },
          select: { id: true },
        });
        userId = user?.id;
      } catch (error) {
        logger.error('Error getting user for audit log:', error);
      }
    }

    // Create audit log entry
    await db.auditLog.create({
      data: {
        userId,
        action: params.action,
        resource: params.resource,
        resourceId: params.resourceId,
        metadata: params.metadata || {},
        ipAddress: params.ipAddress,
        userAgent: params.userAgent,
      },
    });

    return { success: true };
  } catch (error) {
    logger.error('Error logging audit action:', error);
    return { success: false, error: 'Failed to log audit action' };
  }
}

/**
 * Get audit logs with filters
 */
export async function getAuditLogs(filters?: {
  userId?: string;
  action?: string;
  resource?: string;
  limit?: number;
  offset?: number;
}) {
  try {
    const where: any = {};

    if (filters?.userId) {
      where.userId = filters.userId;
    }

    if (filters?.action) {
      where.action = { contains: filters.action, mode: 'insensitive' };
    }

    if (filters?.resource) {
      where.resource = filters.resource;
    }

    const logs = await db.auditLog.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      take: filters?.limit || 50,
      skip: filters?.offset || 0,
    });

    const totalCount = await db.auditLog.count({ where });

    return {
      success: true,
      data: {
        logs,
        totalCount,
      },
    };
  } catch (error) {
    logger.error('Error getting audit logs:', error);
    return { success: false, error: 'Failed to get audit logs' };
  }
}

/**
 * Delete old audit logs (retention policy)
 */
export async function cleanupOldAuditLogs(retentionDays = 90) {
  try {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - retentionDays);

    const result = await db.auditLog.deleteMany({
      where: {
        createdAt: {
          lt: cutoffDate,
        },
      },
    });

    await logAdminAction({
      action: 'audit_logs.cleanup',
      resource: 'AuditLog',
      metadata: {
        deletedCount: result.count,
        retentionDays,
      },
    });

    return {
      success: true,
      data: { deletedCount: result.count },
    };
  } catch (error) {
    logger.error('Error cleaning up audit logs:', error);
    return { success: false, error: 'Failed to cleanup audit logs' };
  }
}
