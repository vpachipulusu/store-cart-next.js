'use server';

import { cookies } from 'next/headers';
import { z } from 'zod';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';

/**
 * Response type for admin SEO actions
 */
type AdminSEOActionResponse<T = any> = {
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
  const permissions = admin.adminUser?.permissions as string[] || [];
  return permissions.includes(permission) || permissions.includes('*');
}

/**
 * SEO Meta schema
 */
const seoMetaSchema = z.object({
  page: z.string().min(1),
  title: z.string().min(1).max(60),
  description: z.string().min(1).max(160),
  keywords: z.string().optional(),
  ogTitle: z.string().max(60).optional(),
  ogDescription: z.string().max(160).optional(),
  ogImage: z.string().url().optional(),
  twitterCard: z.enum(['summary', 'summary_large_image', 'app', 'player']).optional(),
  canonical: z.string().url().optional(),
  noindex: z.boolean().optional(),
  nofollow: z.boolean().optional(),
});

/**
 * Get all SEO meta tags
 */
export async function getAllSEOMetaAction(): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const seoMeta = await db.sEOMeta.findMany({
      orderBy: { page: 'asc' },
    });

    return {
      success: true,
      data: { seoMeta },
    };
  } catch (error: any) {
    logger.error('Get all SEO meta error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get SEO meta',
    };
  }
}

/**
 * Get SEO meta by page
 */
export async function getSEOMetaByPageAction(page: string): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const seoMeta = await db.sEOMeta.findUnique({
      where: { page },
    });

    if (!seoMeta) {
      return {
        success: false,
        error: 'SEO meta not found',
      };
    }

    return {
      success: true,
      data: { seoMeta },
    };
  } catch (error: any) {
    logger.error('Get SEO meta by page error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get SEO meta',
    };
  }
}

/**
 * Create or update SEO meta
 */
export async function upsertSEOMetaAction(
  data: z.infer<typeof seoMetaSchema>
): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = seoMetaSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Upsert SEO meta
    const seoMeta = await db.sEOMeta.upsert({
      where: { page: data.page },
      update: {
        title: data.title,
        description: data.description,
        keywords: data.keywords,
        ogTitle: data.ogTitle,
        ogDescription: data.ogDescription,
        ogImage: data.ogImage,
        twitterCard: data.twitterCard,
        canonical: data.canonical,
        noindex: data.noindex ?? false,
        nofollow: data.nofollow ?? false,
      },
      create: {
        page: data.page,
        title: data.title,
        description: data.description,
        keywords: data.keywords,
        ogTitle: data.ogTitle,
        ogDescription: data.ogDescription,
        ogImage: data.ogImage,
        twitterCard: data.twitterCard || 'summary_large_image',
        canonical: data.canonical,
        noindex: data.noindex ?? false,
        nofollow: data.nofollow ?? false,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'seo.upserted',
        resource: 'SEOMeta',
        resourceId: seoMeta.id,
        metadata: { page: data.page },
      },
    });

    return {
      success: true,
      data: { seoMeta },
    };
  } catch (error: any) {
    logger.error('Upsert SEO meta error:', error);
    return {
      success: false,
      error: error.message || 'Failed to save SEO meta',
    };
  }
}

/**
 * Delete SEO meta
 */
export async function deleteSEOMetaAction(page: string): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.sEOMeta.delete({
      where: { page },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'seo.deleted',
        resource: 'SEOMeta',
        metadata: { page },
      },
    });

    return {
      success: true,
      data: { message: 'SEO meta deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete SEO meta error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete SEO meta',
    };
  }
}

/**
 * URL Redirect schema
 */
const urlRedirectSchema = z.object({
  fromPath: z.string().min(1),
  toPath: z.string().min(1),
  statusCode: z.enum(['301', '302']).transform(Number),
  enabled: z.boolean().optional(),
});

/**
 * Get all URL redirects
 */
export async function getAllURLRedirectsAction(): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.read')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    const redirects = await db.uRLRedirect.findMany({
      orderBy: { createdAt: 'desc' },
    });

    return {
      success: true,
      data: { redirects },
    };
  } catch (error: any) {
    logger.error('Get all URL redirects error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get URL redirects',
    };
  }
}

/**
 * Create URL redirect
 */
export async function createURLRedirectAction(
  data: z.infer<typeof urlRedirectSchema>
): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = urlRedirectSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Create redirect
    const redirect = await db.uRLRedirect.create({
      data: {
        fromPath: data.fromPath,
        toPath: data.toPath,
        statusCode: data.statusCode,
        enabled: data.enabled ?? true,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'redirect.created',
        resource: 'URLRedirect',
        resourceId: redirect.id,
        metadata: { fromPath: data.fromPath, toPath: data.toPath },
      },
    });

    return {
      success: true,
      data: { redirect },
    };
  } catch (error: any) {
    logger.error('Create URL redirect error:', error);
    return {
      success: false,
      error: error.message || 'Failed to create URL redirect',
    };
  }
}

/**
 * Update URL redirect
 */
export async function updateURLRedirectAction(
  id: string,
  data: z.infer<typeof urlRedirectSchema>
): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Validate input
    const validation = urlRedirectSchema.safeParse(data);
    if (!validation.success) {
      return {
        success: false,
        error: validation.error.errors[0].message,
      };
    }

    // Update redirect
    const redirect = await db.uRLRedirect.update({
      where: { id },
      data: {
        fromPath: data.fromPath,
        toPath: data.toPath,
        statusCode: data.statusCode,
        enabled: data.enabled,
      },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'redirect.updated',
        resource: 'URLRedirect',
        resourceId: redirect.id,
        metadata: { fromPath: data.fromPath, toPath: data.toPath },
      },
    });

    return {
      success: true,
      data: { redirect },
    };
  } catch (error: any) {
    logger.error('Update URL redirect error:', error);
    return {
      success: false,
      error: error.message || 'Failed to update URL redirect',
    };
  }
}

/**
 * Delete URL redirect
 */
export async function deleteURLRedirectAction(id: string): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.delete')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    await db.uRLRedirect.delete({
      where: { id },
    });

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'redirect.deleted',
        resource: 'URLRedirect',
        resourceId: id,
      },
    });

    return {
      success: true,
      data: { message: 'URL redirect deleted successfully' },
    };
  } catch (error: any) {
    logger.error('Delete URL redirect error:', error);
    return {
      success: false,
      error: error.message || 'Failed to delete URL redirect',
    };
  }
}

/**
 * Toggle URL redirect status
 */
export async function toggleURLRedirectAction(id: string): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    // Get current redirect
    const currentRedirect = await db.uRLRedirect.findUnique({
      where: { id },
    });

    if (!currentRedirect) {
      return {
        success: false,
        error: 'Redirect not found',
      };
    }

    // Toggle enabled status
    const redirect = await db.uRLRedirect.update({
      where: { id },
      data: { enabled: !currentRedirect.enabled },
    });

    return {
      success: true,
      data: { redirect },
    };
  } catch (error: any) {
    logger.error('Toggle URL redirect error:', error);
    return {
      success: false,
      error: error.message || 'Failed to toggle URL redirect',
    };
  }
}

/**
 * Get active redirect for path
 */
export async function getActiveRedirectAction(fromPath: string): Promise<AdminSEOActionResponse> {
  try {
    const redirect = await db.uRLRedirect.findFirst({
      where: {
        fromPath,
        enabled: true,
      },
    });

    if (!redirect) {
      return {
        success: false,
        error: 'No active redirect found',
      };
    }

    return {
      success: true,
      data: { redirect },
    };
  } catch (error: any) {
    logger.error('Get active redirect error:', error);
    return {
      success: false,
      error: error.message || 'Failed to get redirect',
    };
  }
}

/**
 * Bulk import SEO meta
 */
export async function bulkImportSEOMetaAction(
  seoMetaArray: z.infer<typeof seoMetaSchema>[]
): Promise<AdminSEOActionResponse> {
  try {
    const admin = await getAuthenticatedAdmin();
    if (!admin || !hasPermission(admin, 'seo.write')) {
      return {
        success: false,
        error: 'Unauthorized',
      };
    }

    let successCount = 0;
    let errorCount = 0;
    const errors: string[] = [];

    for (const meta of seoMetaArray) {
      try {
        // Validate each entry
        const validation = seoMetaSchema.safeParse(meta);
        if (!validation.success) {
          errorCount++;
          errors.push(`Invalid data for page ${meta.page}: ${validation.error.errors[0].message}`);
          continue;
        }

        // Upsert SEO meta
        await db.sEOMeta.upsert({
          where: { page: meta.page },
          update: {
            title: meta.title,
            description: meta.description,
            keywords: meta.keywords,
            ogTitle: meta.ogTitle,
            ogDescription: meta.ogDescription,
            ogImage: meta.ogImage,
            twitterCard: meta.twitterCard,
            canonical: meta.canonical,
            noindex: meta.noindex ?? false,
            nofollow: meta.nofollow ?? false,
          },
          create: {
            page: meta.page,
            title: meta.title,
            description: meta.description,
            keywords: meta.keywords,
            ogTitle: meta.ogTitle,
            ogDescription: meta.ogDescription,
            ogImage: meta.ogImage,
            twitterCard: meta.twitterCard || 'summary_large_image',
            canonical: meta.canonical,
            noindex: meta.noindex ?? false,
            nofollow: meta.nofollow ?? false,
          },
        });

        successCount++;
      } catch (error: any) {
        errorCount++;
        errors.push(`Failed to import ${meta.page}: ${error.message}`);
      }
    }

    // Log audit
    await db.auditLog.create({
      data: {
        userId: admin.id,
        action: 'seo.bulk_import',
        resource: 'SEOMeta',
        metadata: { successCount, errorCount },
      },
    });

    return {
      success: true,
      data: {
        message: 'Bulk import completed',
        successCount,
        errorCount,
        errors: errors.length > 0 ? errors : undefined,
      },
    };
  } catch (error: any) {
    logger.error('Bulk import SEO meta error:', error);
    return {
      success: false,
      error: error.message || 'Failed to bulk import SEO meta',
    };
  }
}
