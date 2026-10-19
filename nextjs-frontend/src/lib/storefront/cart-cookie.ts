/**
 * The shopper's cart cookie (KAN-76). Pure, no Next.js imports, so both the server wrapper and tests can use it.
 *
 * The cookie holds only the opaque cart token the backend issued; prices, stock and totals never live in it. It is
 * named per store (`sc_cart_<slug>`) and, on a store subdomain, is also host-only, so one store's token is never sent
 * with another store's requests. httpOnly: page scripts cannot read it. SameSite=Lax: a cross-site POST cannot
 * carry it, so another site cannot change a shopper's cart.
 */

export const CART_COOKIE_PREFIX = 'sc_cart_';
export const CART_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

/** The token shape the backend issues (`secrets.token_urlsafe(32)`); anything else is never sent on. */
const CART_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

/**
 * In production the `__Host-` prefix makes browsers refuse a cookie set with a Domain attribute, so another
 * store's page on a sibling subdomain cannot plant its own cart token (cookie tossing). It needs Secure, which
 * only production uses; plain-http development keeps the bare name.
 */
export function cartCookieName(slug: string): string {
  const prefix = process.env.NODE_ENV === 'production' ? '__Host-' : '';
  return `${prefix}${CART_COOKIE_PREFIX}${slug}`;
}

export function isCartToken(value: unknown): value is string {
  return typeof value === 'string' && CART_TOKEN_PATTERN.test(value);
}

export function cartCookieOptions(): {
  httpOnly: true;
  sameSite: 'lax';
  secure: boolean;
  path: '/';
  maxAge: number;
} {
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: CART_COOKIE_MAX_AGE_SECONDS,
  };
}
