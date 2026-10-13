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

/** The app's own origin (scheme and host only); reads the env at call time. */
function getAppOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_APP_URL || siteConfig.url;
  return new URL(configured).origin;
}

export function buildCheckoutReturnUrls(): { successUrl: string; cancelUrl: string } {
  const origin = getAppOrigin();
  return {
    successUrl: `${origin}${CHECKOUT_RETURN_PATHS.success}`,
    cancelUrl: `${origin}${CHECKOUT_RETURN_PATHS.cancel}`,
  };
}

export function buildBillingPortalReturnUrl(): string {
  return `${getAppOrigin()}${BILLING_PORTAL_RETURN_PATH}`;
}
