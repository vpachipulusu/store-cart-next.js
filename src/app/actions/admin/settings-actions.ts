'use server';

import { cookies } from 'next/headers';
import { revalidateTag } from 'next/cache';
import { z } from 'zod';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * Response type for admin settings actions
 */
type AdminSettingsActionResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
};

/**
 * Get authenticated admin user
 */
async function getAuthenticatedAdmin() {
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

    return user;
  } catch (error) {
    logger.error('Admin authentication error:', error);
    return null;
  }
}

/**
 * Check if user has admin permission
 */
function hasPermission(admin: any, permission: string): boolean {
  const permissions = (admin.adminUser?.permissions as string[]) || [];
  return permissions.includes(permission) || permissions.includes('*');
}

/**
 * App setting schema
 */
const appSettingSchema = z.object({
  key: z.string().min(1),
  value: z.any(),
  category: z.string().min(1),
  description: z.string().optional(),
});

/**
 * Get all app settings
 */
export async function getAllAppSettingsAction(
  category?: string
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const where = category ? { category } : {};

    const settings = await db.appSettings.findMany({
      where,
      orderBy: [{ category: 'asc' }, { key: 'asc' }],
    });

    return {
      success: true,
      data: { settings },
    };
  } catch (error: any) {
    logger.error('Get all app settings error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get app settings',
    };
  }
}

/**
 * Get app setting by key
 */
export async function getAppSettingByKeyAction(key: string): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const setting = await db.appSettings.findUnique({
      where: { key },
    });

    if (!setting) {
      return {
        success: false,
        error: 'Setting not found',
      };
    }

    return {
      success: true,
      data: { setting },
    };
  } catch (error: any) {
    logger.error('Get app setting by key error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get app setting',
    };
  }
}

/**
 * Create or update app setting
 */
export async function upsertAppSettingAction(
  data: z.infer<typeof appSettingSchema>
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = appSettingSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Upsert app setting
    const setting = await db.appSettings.upsert({
      where: { key: data.key },
      update: {
        value: data.value,
        category: data.category,
        description: data.description,
      },
      create: {
        key: data.key,
        value: data.value,
        category: data.category,
        description: data.description,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'settings.upserted',
        resource: 'AppSettings',
        resourceId: setting.id,
        metadata: { key: data.key, category: data.category },
      },
    });

    // Bust theme cache when active theme changes
    if (data.key === 'active_theme') {
      revalidateTag('active-theme', { expire: 3600 });
    }

    // Bust font cache when font changes
    if (data.key === 'app_font') {
      revalidateTag('active-font', { expire: 3600 });
    }

    return {
      success: true,
      data: { setting },
    };
  } catch (error: any) {
    logger.error('Upsert app setting error:', error);
    return {
      success: false,
      error: error.message || 'Failed to save app setting',
    };
  }
}

/**
 * Delete app setting
 */
export async function deleteAppSettingAction(key: string): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.appSettings.delete({
      where: { key },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'settings.deleted',
        resource: 'AppSettings',
        metadata: { key },
      },
    });

    return {
      success: true,
      data: { message: 'App setting deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete app setting error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete app setting',
    };
  }
}

/**
 * Get settings by category
 */
export async function getSettingsByCategoryAction(
  category: string
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const settings = await db.appSettings.findMany({
      where: { category },
      orderBy: { key: 'asc' },
    });

    return {
      success: true,
      data: { settings },
    };
  } catch (error: any) {
    logger.error('Get settings by category error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get settings',
    };
  }
}

/**
 * Feature flag schema
 */
const featureFlagSchema = z.object({
  name: z.string().min(1),
  enabled: z.boolean(),
  description: z.string().optional(),
  rolloutPercentage: z.number().min(0).max(100).optional(),
});

/**
 * Get all feature flags
 */
export async function getAllFeatureFlagsAction(): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const featureFlags = await db.featureFlag.findMany({
      orderBy: { name: 'asc' },
    });

    return {
      success: true,
      data: { featureFlags },
    };
  } catch (error: any) {
    logger.error('Get all feature flags error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get feature flags',
    };
  }
}

/**
 * Get feature flag by name
 */
export async function getFeatureFlagByNameAction(
  name: string
): Promise<AdminSettingsActionResponse> {
  try {
    const featureFlag = await db.featureFlag.findUnique({
      where: { name },
    });

    if (!featureFlag) {
      return {
        success: false,
        error: 'Feature flag not found',
      };
    }

    return {
      success: true,
      data: { featureFlag },
    };
  } catch (error: any) {
    logger.error('Get feature flag by name error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get feature flag',
    };
  }
}

/**
 * Create or update feature flag
 */
export async function upsertFeatureFlagAction(
  data: z.infer<typeof featureFlagSchema>
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = featureFlagSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Upsert feature flag
    const featureFlag = await db.featureFlag.upsert({
      where: { name: data.name },
      update: {
        enabled: data.enabled,
        description: data.description,
        rolloutPercentage: data.rolloutPercentage ?? 0,
      },
      create: {
        name: data.name,
        enabled: data.enabled,
        description: data.description,
        rolloutPercentage: data.rolloutPercentage ?? 0,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'feature_flag.upserted',
        resource: 'FeatureFlag',
        resourceId: featureFlag.id,
        metadata: { name: data.name, enabled: data.enabled },
      },
    });

    return {
      success: true,
      data: { featureFlag },
    };
  } catch (error: any) {
    logger.error('Upsert feature flag error:', error);
    return {
      success: false,
      error: error.message || 'Failed to save feature flag',
    };
  }
}

/**
 * Toggle feature flag
 */
export async function toggleFeatureFlagAction(name: string): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Get current feature flag
    const currentFlag = await db.featureFlag.findUnique({
      where: { name },
    });

    if (!currentFlag) {
      return {
        success: false,
        error: 'Feature flag not found',
      };
    }

    // Toggle enabled status
    const featureFlag = await db.featureFlag.update({
      where: { name },
      data: { enabled: !currentFlag.enabled },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'feature_flag.toggled',
        resource: 'FeatureFlag',
        resourceId: featureFlag.id,
        metadata: { name, enabled: featureFlag.enabled },
      },
    });

    return {
      success: true,
      data: { featureFlag },
    };
  } catch (error: any) {
    logger.error('Toggle feature flag error:', error);
    return {
      success: false,
      error: error.message || 'Failed to toggle feature flag',
    };
  }
}

/**
 * Delete feature flag
 */
export async function deleteFeatureFlagAction(name: string): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.featureFlag.delete({
      where: { name },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'feature_flag.deleted',
        resource: 'FeatureFlag',
        metadata: { name },
      },
    });

    return {
      success: true,
      data: { message: 'Feature flag deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete feature flag error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete feature flag',
    };
  }
}

/**
 * Email template schema
 */
const emailTemplateSchema = z.object({
  name: z.string().min(1),
  subject: z.string().min(1),
  htmlBody: z.string().min(1),
  textBody: z.string().optional(),
  variables: z.array(z.string()).optional(),
});

/**
 * Get all email templates
 */
export async function getAllEmailTemplatesAction(): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const templates = await db.emailTemplate.findMany({
      orderBy: { name: 'asc' },
    });

    return {
      success: true,
      data: { templates },
    };
  } catch (error: any) {
    logger.error('Get all email templates error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get email templates',
    };
  }
}

/**
 * Get email template by name
 */
export async function getEmailTemplateByNameAction(
  name: string
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const template = await db.emailTemplate.findUnique({
      where: { name },
    });

    if (!template) {
      return {
        success: false,
        error: 'Email template not found',
      };
    }

    return {
      success: true,
      data: { template },
    };
  } catch (error: any) {
    logger.error('Get email template by name error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get email template',
    };
  }
}

/**
 * Create or update email template
 */
export async function upsertEmailTemplateAction(
  data: z.infer<typeof emailTemplateSchema>
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = emailTemplateSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Upsert email template
    const template = await db.emailTemplate.upsert({
      where: { name: data.name },
      update: {
        subject: data.subject,
        htmlBody: data.htmlBody,
        textBody: data.textBody,
        variables: data.variables || [],
      },
      create: {
        name: data.name,
        subject: data.subject,
        htmlBody: data.htmlBody,
        textBody: data.textBody,
        variables: data.variables || [],
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'email_template.upserted',
        resource: 'EmailTemplate',
        resourceId: template.id,
        metadata: { name: data.name },
      },
    });

    return {
      success: true,
      data: { template },
    };
  } catch (error: any) {
    logger.error('Upsert email template error:', error);
    return {
      success: false,
      error: error.message || 'Failed to save email template',
    };
  }
}

/**
 * Delete email template
 */
export async function deleteEmailTemplateAction(
  name: string
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.emailTemplate.delete({
      where: { name },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'email_template.deleted',
        resource: 'EmailTemplate',
        metadata: { name },
      },
    });

    return {
      success: true,
      data: { message: 'Email template deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete email template error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete email template',
    };
  }
}

/**
 * Get audit logs
 */
export async function getAuditLogsAction(
  page = 1,
  limit = 50,
  filters?: {
    action?: string;
    resource?: string;
    userId?: string;
  }
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Build where clause
    const where: any = {};

    if (filters?.action) {
      where.action = { contains: filters.action };
    }

    if (filters?.resource) {
      where.resource = filters.resource;
    }

    if (filters?.userId) {
      where.userId = filters.userId;
    }

    const [logs, totalCount] = await Promise.all([
      db.auditLog.findMany({
        where,
        orderBy: { createdAt: 'desc' },
        take: limit,
        skip: (page - 1) * limit,
      }),
      db.auditLog.count({ where }),
    ]);

    return {
      success: true,
      data: {
        logs,
        pagination: {
          page,
          limit,
          totalCount,
          totalPages: Math.ceil(totalCount / limit),
        },
      },
    };
  } catch (error: any) {
    logger.error('Get audit logs error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get audit logs',
    };
  }
}

/**
 * Get system statistics
 */
export async function getSystemStatsAction(): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const [
      totalUsers,
      totalSettings,
      totalFeatureFlags,
      totalEmailTemplates,
      totalSEOMeta,
      totalRedirects,
      totalAuditLogs,
    ] = await Promise.all([
      db.user.count(),
      db.appSettings.count(),
      db.featureFlag.count(),
      db.emailTemplate.count(),
      db.sEOMeta.count(),
      db.uRLRedirect.count(),
      db.auditLog.count(),
    ]);

    return {
      success: true,
      data: {
        totalUsers,
        totalSettings,
        totalFeatureFlags,
        totalEmailTemplates,
        totalSEOMeta,
        totalRedirects,
        totalAuditLogs,
      },
    };
  } catch (error: any) {
    logger.error('Get system stats error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get system statistics',
    };
  }
}

/**
 * Bulk update settings
 */
export async function bulkUpdateSettingsAction(
  settings: z.infer<typeof appSettingSchema>[]
): Promise<AdminSettingsActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'settings.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    let successCount = 0;
    let errorCount = 0;
    const errors: string[] = [];

    for (const setting of settings) {
      try {
        // Validate each entry
        const validation = appSettingSchema.safeParse(setting);
        if (!validation.success) {
          errorCount++;
          errors.push(`Invalid data for key ${setting.key}: ${validation.error.errors[0].message}`);
          continue;
        }

        // Upsert setting
        await db.appSettings.upsert({
          where: { key: setting.key },
          update: {
            value: setting.value,
            category: setting.category,
            description: setting.description,
          },
          create: {
            key: setting.key,
            value: setting.value,
            category: setting.category,
            description: setting.description,
          },
        });

        successCount++;
      } catch (error: any) {
        errorCount++;
        errors.push(`Failed to update ${setting.key}: ${error.message}`);
      }
    }

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'settings.bulk_update',
        resource: 'AppSettings',
        metadata: { successCount, errorCount },
      },
    });

    return {
      success: true,
      data: {
        message: 'Bulk update completed',
        successCount,
        errorCount,
        errors: errors.length > 0 ? errors : undefined,
      },
    };
  } catch (error: any) {
    logger.error('Bulk update settings error:', error);
    return {
      success: false,
      error: error.message || 'Failed to bulk update settings',
    };
  }
}
