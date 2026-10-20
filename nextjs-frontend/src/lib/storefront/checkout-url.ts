/**
 * Pure URL rules for the storefront checkout handoff (KAN-77); no Next.js imports, so server code, the browser and
 * tests share them.
 */

const STRIPE_CHECKOUT_HOST = 'checkout.stripe.com';

/**
 * The single-host allowlist is intentional: Checkout Sessions (direct charges on a connected account included) are
 * always hosted on `checkout.stripe.com`. Another Stripe host, a custom domain or a subdomain is refused on purpose, so
 * widening this needs a decision, not a tweak.
 *
 * True only for an https URL on exactly `checkout.stripe.com` (no userinfo, no port). The backend returns this URL
 * and the shopper's browser is sent to it, so anything else is never followed.
 */
export function isStripeCheckoutUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value === '') return false;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  return (
    url.protocol === 'https:' &&
    url.hostname === STRIPE_CHECKOUT_HOST &&
    url.port === '' &&
    url.username === '' &&
    url.password === ''
  );
}

/**
 * Where Stripe sends the shopper back to: pages on the store's own host. The success URL carries no order id (it is
 * not known before the backend creates the order) and the success page trusts nothing in its query anyway.
 */
export function checkoutReturnUrls(origin: string): { successUrl: string; cancelUrl: string } {
  return {
    successUrl: `${origin}/checkout/success`,
    cancelUrl: `${origin}/checkout/cancel`,
  };
}
