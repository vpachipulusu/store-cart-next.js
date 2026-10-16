/** KAN-227: auth errors are classified into copy that never reveals whether an account exists. */
import { describe, expect, it } from 'vitest';
import { getFirebaseErrorMessage } from '@/lib/utils/firebase-errors';
import { classifyAuthError, classifyThrownAuthError } from '@/components/auth/auth-form-errors';

const fromCode = (code: string) => getFirebaseErrorMessage({ code });

describe('classifyAuthError', () => {
  it.each(['auth/user-not-found', 'auth/wrong-password', 'auth/invalid-credential'])(
    'sign-in %s gives the same neutral credentials copy',
    (code) => {
      const result = classifyAuthError(fromCode(code), 'sign-in');

      expect(result.title).toBe('We could not sign you in');
      expect(result.message).toBe(
        'That email and password do not match. Check them and try again, or reset your password.'
      );
    }
  );

  it('marks a missing account so the reset flow can stay neutral', () => {
    expect(classifyAuthError(fromCode('auth/user-not-found'), 'reset').kind).toBe(
      'account-missing'
    );
  });

  it('sign-up email in use does not say the email is registered', () => {
    const result = classifyAuthError(fromCode('auth/email-already-in-use'), 'sign-up');

    expect(result.title).toBe('We could not create your account');
    expect(`${result.title} ${result.message}`).not.toMatch(/already registered|in use|exists/i);
  });

  it('classifies network failures', () => {
    const result = classifyAuthError(fromCode('auth/network-request-failed'), 'sign-in');

    expect(result.kind).toBe('network');
    expect(result.title).toBe('We could not reach StoreCart');
    expect(result.message).toBe('Check your connection and try again.');
  });

  it('classifies rate limiting and states the wait', () => {
    const result = classifyAuthError(fromCode('auth/too-many-requests'), 'sign-in');

    expect(result.kind).toBe('rate-limit');
    expect(result.message).toMatch(/wait a few minutes/i);
  });

  it('classifies suspended accounts', () => {
    const result = classifyAuthError(fromCode('auth/user-disabled'), 'sign-in');

    expect(result.kind).toBe('suspended');
    expect(result.title).toBe('This account is suspended');
    expect(result.message).toMatch(/mistake/i);
  });

  it('falls back to a generic message and never echoes raw text', () => {
    const result = classifyAuthError('Token verification failed', 'sign-in');

    expect(result.kind).toBe('unknown');
    expect(`${result.title} ${result.message}`).not.toMatch(/token/i);
  });

  it('asks for a stronger password instead of blaming the server', () => {
    const result = classifyAuthError(fromCode('auth/weak-password'), 'sign-up');

    expect(result.kind).toBe('weak-password');
    expect(result.message).toBe('Choose a stronger password and try again.');
  });

  it('has a distinct message for every mapped code, so message matching cannot collide', () => {
    const codes = [
      'auth/invalid-credential',
      'auth/wrong-password',
      'auth/invalid-email',
      'auth/email-already-in-use',
      'auth/account-exists-with-different-credential',
      'auth/user-not-found',
      'auth/network-request-failed',
      'auth/too-many-requests',
      'auth/quota-exceeded',
      'auth/user-disabled',
      'auth/weak-password',
    ];
    const messages = codes.map(fromCode);

    expect(new Set(messages).size).toBe(codes.length);
  });

  it('treats only a TypeError or a Firebase network code as a network failure when thrown', () => {
    expect(classifyThrownAuthError(new TypeError('Failed to fetch'), 'sign-in').kind).toBe(
      'network'
    );
    expect(classifyThrownAuthError({ code: 'auth/network-request-failed' }, 'sign-in').kind).toBe(
      'network'
    );
    expect(classifyThrownAuthError(new Error('boom'), 'sign-in').kind).toBe('unknown');
  });
});
