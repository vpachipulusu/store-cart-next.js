import Stripe from 'stripe';

let stripeClient: Stripe | null = null;

/**
 * Server-side Stripe client, created on first use.
 *
 * Never create a Stripe client at module scope: `next build` imports every route and server-action module while
 * collecting page data, so a module-scope client makes the build require STRIPE_SECRET_KEY (KAN-134).
 */
export function getStripeServerClient(): Stripe {
  if (!process.env.STRIPE_SECRET_KEY) {
    throw new Error('STRIPE_SECRET_KEY is not defined. Please add it to your .env file.');
  }

  if (!stripeClient) {
    stripeClient = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: '2025-08-27.basil',
      typescript: true,
    });
  }

  return stripeClient;
}
