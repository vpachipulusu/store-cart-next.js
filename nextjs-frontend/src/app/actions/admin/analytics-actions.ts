'use server';

import { revalidatePath } from 'next/cache';
import { logger } from '@/lib/logger';
import { ADMIN_SYNC_RATE_LIMITED_MESSAGE, adminErrorMessage } from '@/lib/api/admin-errors';
import { syncAdminSubscriptions, type SyncData } from '@/lib/api/admin-analytics';

/**
 * Bulk Stripe subscription reconciliation (KAN-119). The API authenticates the session, checks
 * `subscriptions.sync` and writes the audit row; this action only calls the wrapper and turns a failure into a
 * curated message. The sync reports drift and changes no subscription, so a repeat is harmless.
 */

type SyncActionResponse = { success: true; data: SyncData } | { success: false; error: string };

export async function syncStripeSubscriptionsAction(): Promise<SyncActionResponse> {
  const result = await syncAdminSubscriptions();
  if (!result.success) {
    if (result.status === 429) return { success: false, error: ADMIN_SYNC_RATE_LIMITED_MESSAGE };
    if (result.status !== 401 && result.status !== 403) {
      logger.error('Admin subscription sync failed', { status: result.status });
    }
    return { success: false, error: adminErrorMessage(result) };
  }
  revalidatePath('/admin/subscriptions');
  return { success: true, data: result.data };
}
