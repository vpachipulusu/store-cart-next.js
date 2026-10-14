/**
 * Stripe Webhook API Route Handler
 *
 * Handles all Stripe webhook events
 */

import { NextRequest, NextResponse } from 'next/server';
import { headers } from 'next/headers';
import { verifyWebhookSignature } from '@/lib/stripe/webhooks';
import { processWebhookEvent } from '@/lib/stripe/webhook-processing';
import { logger } from '@/lib/logger';

/**
 * POST /api/webhooks/stripe
 *
 * Process Stripe webhook events
 */
export async function POST(request: NextRequest) {
  try {
    // Get raw body as text
    const body = await request.text();

    // Get signature from headers
    const headersList = await headers();
    const signature = headersList.get('stripe-signature');

    if (!signature) {
      logger.error('Missing stripe-signature header');
      return NextResponse.json({ error: 'Missing signature header' }, { status: 400 });
    }

    // Verify webhook signature and construct event
    let event;
    try {
      event = verifyWebhookSignature(body, signature);
    } catch (error) {
      logger.error('Webhook signature verification failed:', error);
      return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
    }

    logger.info(`Received webhook event: ${event.type}`);

    // Handle the event once. A failure returns 5xx so Stripe retries.
    let result;
    try {
      result = await processWebhookEvent(event);
    } catch (error) {
      logger.error(`Error handling webhook event ${event.type} (${event.id}):`, error);

      return NextResponse.json({ error: 'Webhook processing failed' }, { status: 500 });
    }

    return NextResponse.json(
      {
        received: true,
        eventId: event.id,
        eventType: event.type,
        ...(result === 'duplicate' ? { duplicate: true } : {}),
      },
      { status: 200 }
    );
  } catch (error) {
    logger.error('Webhook error:', error);

    return NextResponse.json({ error: 'Webhook processing failed' }, { status: 500 });
  }
}

/**
 * Next.js Route Config
 * Disable body parsing to get raw body for signature verification
 */
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
// Keep below WEBHOOK_LEASE_MS (60 s) so a handler cannot outlive its processing lease.
export const maxDuration = 30;
