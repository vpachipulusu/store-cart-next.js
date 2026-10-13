/**
 * Idempotent Stripe webhook processing (KAN-128)
 *
 * Records each Stripe event id (unique primary key) so a retried or duplicate
 * delivery is not applied twice. A row without processedAt means an earlier
 * attempt failed, so the event is processed again.
 */

import type Stripe from 'stripe';
import { Prisma } from '@prisma/client';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';
import { handleWebhookEvent } from './webhooks';

export type WebhookProcessingResult = 'processed' | 'duplicate';

const UNIQUE_CONSTRAINT_CODE = 'P2002';

function isUniqueViolation(error: unknown): boolean {
  return (
    error instanceof Prisma.PrismaClientKnownRequestError && error.code === UNIQUE_CONSTRAINT_CODE
  );
}

/**
 * Process an event once. Throws if the handler or the bookkeeping fails, so the
 * caller can ask Stripe to retry.
 */
export async function processWebhookEvent(event: Stripe.Event): Promise<WebhookProcessingResult> {
  try {
    await db.processedStripeEvent.create({ data: { id: event.id, type: event.type } });
  } catch (error) {
    if (!isUniqueViolation(error)) {
      throw error;
    }
    const existing = await db.processedStripeEvent.findUnique({ where: { id: event.id } });
    if (existing?.processedAt) {
      logger.info(`Skipping duplicate Stripe event ${event.id}`);
      return 'duplicate';
    }
    logger.warn(`Reprocessing Stripe event ${event.id} after an earlier failed attempt`);
  }

  await handleWebhookEvent(event);

  await db.processedStripeEvent.update({
    where: { id: event.id },
    data: { processedAt: new Date() },
  });

  return 'processed';
}
