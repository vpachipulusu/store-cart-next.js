import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sentry = vi.hoisted(() => ({ captureException: vi.fn(), addBreadcrumb: vi.fn() }));
vi.mock('@sentry/nextjs', () => sentry);

import { logger } from '@/lib/logger';

// jsdom defines `window`, so the logger takes its console path instead of Winston.
const EMAIL = ['jane.doe', 'example.com'].join('@');
const UID = 'aB3dE5gH7jK9mN1pQ3sT5vX7yZ2c';
const STRIPE_KEY = ['sk', 'live', 'abcdefghijklmnop1234'].join('_');

describe('logger console path', () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
  });

  it('prints only name, code and a redacted message for an Error', () => {
    const err = Object.assign(new Error(`bad ${EMAIL} ${UID} ${STRIPE_KEY}`), {
      name: 'FirebaseAuthError',
      code: 'auth/id-token-expired',
    });

    logger.error(`Verify token error for ${EMAIL}:`, err);

    expect(errorSpy).toHaveBeenCalledTimes(1);
    const [printedMessage, printedMeta] = errorSpy.mock.calls[0];
    const printed = JSON.stringify([printedMessage, printedMeta]);
    for (const leak of [EMAIL, UID, STRIPE_KEY]) {
      expect(printed).not.toContain(leak);
    }
    expect(Object.keys(printedMeta).sort()).toEqual(['code', 'message', 'name']);
    expect(printedMeta.code).toBe('auth/id-token-expired');
  });
});
