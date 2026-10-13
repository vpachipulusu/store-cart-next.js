// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { isSessionVerificationError } from '@/lib/auth/session-errors';

const SESSION_CODES = [
  'auth/session-cookie-expired',
  'auth/session-cookie-revoked',
  'auth/id-token-revoked',
  'auth/user-disabled',
  'auth/user-not-found',
  'auth/invalid-session-cookie',
  'auth/argument-error',
];

describe('isSessionVerificationError', () => {
  it.each(SESSION_CODES)('returns true for firebase-admin code %s', (code) => {
    expect(isSessionVerificationError({ code, message: 'x' })).toBe(true);
  });

  it('returns false for other firebase auth codes', () => {
    expect(isSessionVerificationError({ code: 'auth/quota-exceeded' })).toBe(false);
    expect(isSessionVerificationError({ code: 'auth/internal-error' })).toBe(false);
  });

  it('returns false for database-style and generic errors', () => {
    expect(isSessionVerificationError({ code: 'P1001', message: 'db down' })).toBe(false);
    expect(isSessionVerificationError(new Error('auth/session-cookie-expired'))).toBe(false);
  });

  it('returns false for redirect errors, non-objects and nullish values', () => {
    expect(isSessionVerificationError({ digest: 'NEXT_REDIRECT;replace;/login;307;' })).toBe(false);
    expect(isSessionVerificationError('auth/session-cookie-expired')).toBe(false);
    expect(isSessionVerificationError(null)).toBe(false);
    expect(isSessionVerificationError(undefined)).toBe(false);
    expect(isSessionVerificationError({ code: 42 })).toBe(false);
  });
});
