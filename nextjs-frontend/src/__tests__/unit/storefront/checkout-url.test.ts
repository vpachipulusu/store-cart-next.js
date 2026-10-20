/** KAN-77: only a Stripe-hosted https URL is ever followed, and return URLs stay on the store's own origin. */
import { describe, expect, it } from 'vitest';
import { checkoutReturnUrls, isStripeCheckoutUrl } from '@/lib/storefront/checkout-url';

describe('isStripeCheckoutUrl', () => {
  it('accepts a Stripe Checkout session URL', () => {
    expect(isStripeCheckoutUrl('https://checkout.stripe.com/c/pay/cs_test_a1#frag')).toBe(true);
  });

  it.each([
    ['http scheme', 'http://checkout.stripe.com/c/pay/x'],
    ['another host', 'https://evil.example/c/pay/x'],
    ['lookalike suffix', 'https://checkout.stripe.com.evil.example/x'],
    ['lookalike prefix', 'https://evilcheckout.stripe.com/x'],
    ['userinfo trick', 'https://checkout.stripe.com@evil.example/x'],
    ['explicit port', 'https://checkout.stripe.com:8443/x'],
    ['javascript scheme', 'javascript:alert(1)'],
    ['relative path', '/c/pay/x'],
    ['empty', ''],
    ['not a string', 42],
    ['null', null],
    ['undefined', undefined],
    ['a trailing-dot host', 'https://checkout.stripe.com./x'],
    ['a password only', 'https://:pw@checkout.stripe.com/x'],
  ])('refuses %s', (_label, value) => {
    expect(isStripeCheckoutUrl(value)).toBe(false);
  });
});

describe('checkoutReturnUrls', () => {
  it('builds success and cancel URLs on the store origin', () => {
    expect(checkoutReturnUrls('https://acme.storecart.com')).toEqual({
      successUrl: 'https://acme.storecart.com/checkout/success',
      cancelUrl: 'https://acme.storecart.com/checkout/cancel',
    });
  });

  it('keeps the development port', () => {
    expect(checkoutReturnUrls('http://acme.localhost:3100').successUrl).toBe(
      'http://acme.localhost:3100/checkout/success'
    );
  });
});
