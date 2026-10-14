/**
 * Idempotent Stripe webhook processing (KAN-128)
 *
 * Each Stripe event id is claimed by inserting a row (primary key). The claim
 * is a lease (claimedAt): a concurrent delivery that finds a live lease fails
 * so Stripe retries later, and only an expired lease can be taken over, with a
 * conditional update that must affect exactly one row. processedAt is set only
 * after the handler succeeds; on failure the claim is released.
 */

import type Stripe from 'stripe';
import { Prisma } from '@prisma/client';
import { db } from '@/lib/db/client';
import { logger } from '@/lib/logger';
import { handleWebhookEvent } from './webhooks';

export type WebhookProcessingResult = 'processed' | 'duplicate';

// The webhook route's maxDuration (30 s) must stay below this lease.
export const WEBHOOK_LEASE_MS = 60_000;

const UNIQUE_CONSTRAINT_CODE = 'P2002';

export class WebhookInProgressError extends Error {
  constructor(eventId: string) {
    super(`Stripe event ${eventId} is being processed by another delivery`);
    this.name = 'WebhookInProgressError';
  }
}

function isUniqueViolation(error: unknown): boolean {
  return (
    error instanceof Prisma.PrismaClientKnownRequestError && error.code === UNIQUE_CONSTRAINT_CODE
  );
}

/** Returns 'duplicate' if already processed; throws if another delivery holds the claim. */
async function claimExistingEvent(
  eventId: string,
  claimedAt: Date
): Promise<'claimed' | 'duplicate'> {
  const existing = await db.processedStripeEvent.findUnique({ where: { id: eventId } });
  if (!existing) {
    // Released between our insert and read: let Stripe retry.
    throw new WebhookInProgressError(eventId);
  }
  if (existing.processedAt) {
    logger.info(`Skipping duplicate Stripe event ${eventId}`);
    return 'duplicate';
  }
  if (Date.now() - existing.claimedAt.getTime() < WEBHOOK_LEASE_MS) {
    throw new WebhookInProgressError(eventId);
  }

  const takeover = await db.processedStripeEvent.updateMany({
    where: { id: eventId, processedAt: null, claimedAt: existing.claimedAt },
    data: { claimedAt },
  });
  if (takeover.count !== 1) {
    throw new WebhookInProgressError(eventId);
  }
  logger.warn(`Took over expired claim on Stripe event ${eventId}`);
  return 'claimed';
}

/** Releases only our own claim: a new owner after lease expiry has a different claimedAt. */
async function releaseClaim(eventId: string, claimedAt: Date): Promise<void> {
  try {
    await db.processedStripeEvent.deleteMany({
      where: { id: eventId, processedAt: null, claimedAt },
    });
  } catch (error) {
    logger.error(`Failed to release claim on Stripe event ${eventId}:`, error);
  }
}

/**
 * Process an event once. Throws if the handler or the bookkeeping fails, or if
 * another delivery is processing it, so the caller asks Stripe to retry.
 */
export async function processWebhookEvent(event: Stripe.Event): Promise<WebhookProcessingResult> {
  const claimedAt = new Date();
  try {
    await db.processedStripeEvent.create({ data: { id: event.id, type: event.type, claimedAt } });
  } catch (error) {
    if (!isUniqueViolation(error)) {
      throw error;
    }
    if ((await claimExistingEvent(event.id, claimedAt)) === 'duplicate') {
      return 'duplicate';
    }
  }

  try {
    await handleWebhookEvent(event);
  } catch (error) {
    await releaseClaim(event.id, claimedAt);
    throw error;
  }

  await db.processedStripeEvent.update({
    where: { id: event.id },
    data: { processedAt: new Date() },
  });

  return 'processed';
}
