/**
 * Stripe Webhook API Route Handler
 *
 * Handles all Stripe webhook events
 */

import { NextRequest, NextResponse } from 'next/server';
import { headers } from 'next/headers';
import { verifyWebhookSignature, handleWebhookEvent } from '@/lib/stripe/webhooks';
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
      return NextResponse.json(
        { error: 'Missing signature header' },
        { status: 400 }
      );
    }

    // Verify webhook signature and construct event
    let event;
    try {
      event = verifyWebhookSignature(body, signature);
    } catch (error) {
      logger.error('Webhook signature verification failed:', error);
      return NextResponse.json(
        { error: 'Invalid signature' },
        { status: 401 }
      );
    }

    logger.info(`Received webhook event: ${event.type}`);

    // Handle the event
    try {
      await handleWebhookEvent(event);
    } catch (error) {
      logger.error(`Error handling webhook event ${event.type}:`, error);

      // Return 200 to acknowledge receipt even if processing fails
      // This prevents Stripe from retrying immediately
      return NextResponse.json(
        {
          received: true,
          error: 'Event processing failed',
          eventId: event.id,
        },
        { status: 200 }
      );
    }

    // Return success response
    return NextResponse.json(
      {
        received: true,
        eventId: event.id,
        eventType: event.type,
      },
      { status: 200 }
    );
  } catch (error) {
    logger.error('Webhook error:', error);

    return NextResponse.json(
      { error: 'Webhook processing failed' },
      { status: 500 }
    );
  }
}

/**
 * OPTIONS /api/webhooks/stripe
 *
 * Handle CORS preflight
 */
export async function OPTIONS() {
  return new NextResponse(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, stripe-signature',
    },
  });
}

/**
 * Next.js Route Config
 * Disable body parsing to get raw body for signature verification
 */
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
