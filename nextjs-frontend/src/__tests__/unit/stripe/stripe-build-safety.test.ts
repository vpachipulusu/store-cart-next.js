// @vitest-environment node
/**
 * Regression tests for KAN-134: `next build` imports every route and server-action module while collecting page
 * data, so no module may create a Stripe client at import time. A build must not need STRIPE_SECRET_KEY.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/firebase/admin', () => ({ getAdminAuth: vi.fn() }));
vi.mock('@/lib/db/client', () => ({ db: {} }));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/utils/notifications', () => ({}));

const SECRET_NAME = 'STRIPE_SECRET_KEY';

describe('KAN-134: Stripe clients are created on first use, not at import', () => {
  let savedSecret: string | undefined;

  beforeEach(() => {
    savedSecret = process.env[SECRET_NAME];
    delete process.env[SECRET_NAME];
    vi.resetModules();
  });

  afterEach(() => {
    if (savedSecret === undefined) delete process.env[SECRET_NAME];
    else process.env[SECRET_NAME] = savedSecret;
  });

  it.each([
    ['webhook handlers', '@/lib/stripe/webhooks'],
    ['subscription actions', '@/app/actions/subscription-actions'],
    ['admin subscription actions', '@/app/actions/admin/subscription-actions'],
  ])('imports the %s without the secret key', async (_name, modulePath) => {
    await expect(import(modulePath)).resolves.toBeDefined();
  });

  it('no longer exports a module-scope Stripe client from the webhook handlers', async () => {
    const webhooks = await import('@/lib/stripe/webhooks');
    expect(webhooks).not.toHaveProperty('stripe');
  });

  it('fails clearly at first use when the key is missing', async () => {
    const { getStripeServerClient } = await import('@/lib/stripe/server');
    expect(() => getStripeServerClient()).toThrow(/STRIPE_SECRET_KEY is not defined/);
  });

  it('creates one client on first use and reuses it', async () => {
    process.env[SECRET_NAME] = 'sk_test_placeholder_for_unit_test';
    const { getStripeServerClient } = await import('@/lib/stripe/server');

    const first = getStripeServerClient();

    expect(first).toBe(getStripeServerClient());
  });
});
