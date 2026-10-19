// @vitest-environment node
/** KAN-76: the cart cookie is named per store, httpOnly, SameSite=Lax, and only a well-formed token is accepted. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CART_COOKIE_MAX_AGE_SECONDS,
  cartCookieName,
  cartCookieOptions,
  isCartToken,
} from '@/lib/storefront/cart-cookie';

describe('cart cookie', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('is named per store so stores never share a cart', () => {
    expect(cartCookieName('acme')).toBe('sc_cart_acme');
    expect(cartCookieName('acme')).not.toBe(cartCookieName('beta'));
  });

  it('is httpOnly, lax, site-wide and lives 30 days', () => {
    const options = cartCookieOptions();

    expect(options).toMatchObject({ httpOnly: true, sameSite: 'lax', path: '/' });
    expect(options.maxAge).toBe(CART_COOKIE_MAX_AGE_SECONDS);
    expect(CART_COOKIE_MAX_AGE_SECONDS).toBe(2_592_000);
  });

  it('is secure in production only', () => {
    vi.stubEnv('NODE_ENV', 'production');
    expect(cartCookieOptions().secure).toBe(true);
    vi.stubEnv('NODE_ENV', 'development');
    expect(cartCookieOptions().secure).toBe(false);
  });

  it('uses the __Host- prefix in production: Secure, path / and no Domain', () => {
    vi.stubEnv('NODE_ENV', 'production');

    const options = cartCookieOptions();

    expect(cartCookieName('acme')).toBe('__Host-sc_cart_acme');
    expect(options).toMatchObject({ secure: true, path: '/' });
    expect(options).not.toHaveProperty('domain');
  });

  it('accepts a 43 character url-safe token and nothing else', () => {
    expect(isCartToken('A'.repeat(43))).toBe(true);
    expect(isCartToken('a-_B'.repeat(10) + 'abc')).toBe(true);
    for (const bad of [undefined, null, 42, '', 'short', 'A'.repeat(44), `${'A'.repeat(42)}!`]) {
      expect(isCartToken(bad)).toBe(false);
    }
  });
});
