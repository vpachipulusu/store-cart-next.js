/**
 * Stripe return URLs (KAN-127). Clients never supply them: they are built on the server from the app's own origin
 * and fixed paths, so a hostile caller cannot turn checkout or the billing portal into an open redirect.
 */
import { siteConfig } from '@/config/site';

export const CHECKOUT_RETURN_PATHS = {
  success: '/dashboard?upgrade=success',
  cancel: '/pricing?upgrade=cancelled',
} as const;

export const BILLING_PORTAL_RETURN_PATH = '/dashboard/settings/billing';

/**
 * The app's own origin (scheme and host only); reads the env at call time.
 * - Production (not a Vercel preview): NEXT_PUBLIC_APP_URL is required and must be a valid URL, else this throws.
 * - Vercel preview/development with it unset: https://${VERCEL_URL}.
 * - Local and test: falls back to the site config (localhost).
 */
function getAppOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_APP_URL;
  const isProduction =
    process.env.NODE_ENV === 'production' && process.env.VERCEL_ENV !== 'preview';

  if (isProduction) {
    if (!configured) {
      throw new Error('NEXT_PUBLIC_APP_URL must be set in production to build Stripe return URLs.');
    }
    try {
      return new URL(configured).origin;
    } catch {
      throw new Error('NEXT_PUBLIC_APP_URL is not a valid URL; cannot build Stripe return URLs.');
    }
  }

  if (!configured && process.env.VERCEL_URL) {
    return new URL(`https://${process.env.VERCEL_URL}`).origin;
  }
  return new URL(configured || siteConfig.url).origin;
}

export function buildCheckoutReturnUrls(): { successUrl: string; cancelUrl: string } {
  const origin = getAppOrigin();
  return {
    successUrl: `${origin}${CHECKOUT_RETURN_PATHS.success}`,
    cancelUrl: `${origin}${CHECKOUT_RETURN_PATHS.cancel}`,
  };
}

export const CONNECT_RETURN_PATHS = {
  returned: '/dashboard/settings?connect=return',
  refresh: '/dashboard/settings?connect=refresh',
} as const;

/** Where Stripe-hosted Connect onboarding sends the merchant back to (KAN-67); built on the server. */
export function buildConnectReturnUrls(): { returnUrl: string; refreshUrl: string } {
  const origin = getAppOrigin();
  return {
    returnUrl: `${origin}${CONNECT_RETURN_PATHS.returned}`,
    refreshUrl: `${origin}${CONNECT_RETURN_PATHS.refresh}`,
  };
}

export function buildBillingPortalReturnUrl(): string {
  return `${getAppOrigin()}${BILLING_PORTAL_RETURN_PATH}`;
}
