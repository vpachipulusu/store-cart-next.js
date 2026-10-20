import { z } from 'zod';
import { isStripeCheckoutUrl } from './checkout-url';

/**
 * Browser call to this store's own checkout route handler (KAN-77). Same-origin relative URL only: the page is on
 * the store host, so the httpOnly cart cookie and `Origin` go with it. The browser never calls the backend, and it
 * only ever follows a Stripe-hosted URL.
 */

export type CheckoutReply = { ok: true; url: string } | { ok: false; error: string };

const FALLBACK_ERROR = 'Checkout could not be started. Please try again.';

/** The only reply that sends the browser anywhere: success with a Stripe-hosted URL. */
const successSchema = z.object({
  success: z.literal(true),
  data: z.object({ checkoutUrl: z.string().refine(isStripeCheckoutUrl) }),
});
const failureSchema = z.object({ error: z.string().min(1) });

export async function startCheckout(): Promise<CheckoutReply> {
  let response: Response;
  try {
    response = await fetch('/checkout', { method: 'POST', cache: 'no-store' });
  } catch {
    return { ok: false, error: FALLBACK_ERROR };
  }
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  const success = successSchema.safeParse(parsed);
  if (response.ok && success.success) return { ok: true, url: success.data.data.checkoutUrl };
  const failure = failureSchema.safeParse(parsed);
  return { ok: false, error: failure.success ? failure.data.error : FALLBACK_ERROR };
}
