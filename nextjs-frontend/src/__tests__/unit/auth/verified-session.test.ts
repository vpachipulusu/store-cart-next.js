// @vitest-environment node
/**
 * KAN-123: the legacy server boundary must decide on the signed `email_verified` claim in the
 * revocation-checked session cookie, never on the client-writable `email-verified` cookie.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  cookieJar: new Map<string, string>(),
  fetchSessionStatus: vi.fn(),
  fetchProfile: vi.fn(),
  loggerError: vi.fn(),
  loggerWarn: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) =>
      mocks.cookieJar.has(name) ? { value: mocks.cookieJar.get(name) } : undefined,
  }),
}));
vi.mock('@/lib/api/account', () => ({
  fetchProfile: mocks.fetchProfile,
  fetchSessionStatus: mocks.fetchSessionStatus,
}));
vi.mock('@/lib/logger', () => ({
  logger: { error: mocks.loggerError, warn: mocks.loggerWarn },
}));

import {
  EmailNotVerifiedError,
  getVerifiedSessionClaims,
  getVerifiedUserId,
  isEmailNotVerifiedError,
  readSessionStatus,
  verifyVerifiedSessionCookie,
} from '@/lib/auth/verified-session';

const REVOKED_RESULT = { success: false, error: 'Invalid authentication', status: 401 };
const OUTAGE_RESULT = { success: false, error: 'Backend unavailable' };
const ok = (data: unknown) => ({ success: true, data });
const REVOKED = Object.assign(new Error('revoked'), { code: 'auth/session-cookie-revoked' });
const verifiedClaims = { uid: 'uid-1', email: 'a@b.test', email_verified: true };
const unverifiedClaims = { uid: 'uid-1', email: 'a@b.test', email_verified: false };

describe('verified-session boundary (KAN-123)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cookieJar.clear();
    mocks.cookieJar.set('session', 'session-cookie');
    mocks.fetchSessionStatus.mockResolvedValue(ok(verifiedClaims));
    mocks.fetchProfile.mockResolvedValue({
      success: true,
      data: { id: 'user-1', email: 'a@b.test', email_verified: true },
    });
  });

  it('verifies through the backend session status (which checks revocation), not locally', async () => {
    const claims = await verifyVerifiedSessionCookie();

    expect(claims).toEqual(verifiedClaims);
    expect(mocks.fetchSessionStatus).toHaveBeenCalledTimes(1);
  });

  it('authorizes a verified user', async () => {
    expect(await getVerifiedUserId()).toBe('user-1');
  });

  describe('unverified user', () => {
    beforeEach(() => mocks.fetchSessionStatus.mockResolvedValue(ok(unverifiedClaims)));

    it('is rejected with EmailNotVerifiedError', async () => {
      const error = await verifyVerifiedSessionCookie().catch((e) => e);

      expect(error).toBeInstanceOf(EmailNotVerifiedError);
      expect(isEmailNotVerifiedError(error)).toBe(true);
    });

    it('gets no user id and never reaches the backend', async () => {
      expect(await getVerifiedUserId()).toBeNull();
      expect(mocks.fetchProfile).not.toHaveBeenCalled();
    });

    it('is rejected when the claim is missing entirely', async () => {
      mocks.fetchSessionStatus.mockResolvedValue(ok({ uid: 'uid-1', email: 'a@b.test' }));

      expect(await getVerifiedUserId()).toBeNull();
    });
  });

  describe('forged email-verified cookie', () => {
    it('does not authorize an unverified user who sets email-verified=true', async () => {
      mocks.cookieJar.set('email-verified', 'true');
      mocks.fetchSessionStatus.mockResolvedValue(ok(unverifiedClaims));

      expect(await getVerifiedUserId()).toBeNull();
      await expect(getVerifiedSessionClaims()).rejects.toBeInstanceOf(EmailNotVerifiedError);
    });
  });

  describe('stale email-verified cookie', () => {
    it('does not block a user whose claim is verified but whose cookie still says false', async () => {
      mocks.cookieJar.set('email-verified', 'false');

      expect(await getVerifiedUserId()).toBe('user-1');
    });
  });

  describe('missing email-verified cookie', () => {
    it('does not authorize an unverified user with no cookie at all', async () => {
      mocks.cookieJar.delete('email-verified');
      mocks.fetchSessionStatus.mockResolvedValue(ok(unverifiedClaims));

      expect(await getVerifiedUserId()).toBeNull();
    });

    it('still authorizes a verified user (the cookie is irrelevant)', async () => {
      mocks.cookieJar.delete('email-verified');

      expect(await getVerifiedUserId()).toBe('user-1');
    });
  });

  describe('revoked or invalid session', () => {
    it('rejects a revoked session (401 Invalid authentication) with the invalid-session code', async () => {
      mocks.fetchSessionStatus.mockResolvedValue(REVOKED_RESULT);

      expect(await getVerifiedUserId()).toBeNull();
      await expect(getVerifiedSessionClaims()).rejects.toMatchObject({
        code: 'auth/invalid-session-cookie',
      });
    });

    it('rejects a revoked session even with email-verified=true', async () => {
      mocks.cookieJar.set('email-verified', 'true');
      mocks.fetchSessionStatus.mockResolvedValue(REVOKED_RESULT);

      expect(await getVerifiedUserId()).toBeNull();
    });
  });

  describe('readSessionStatus', () => {
    it('returns the claims, unverified email included', async () => {
      mocks.fetchSessionStatus.mockResolvedValue(ok(unverifiedClaims));

      expect(await readSessionStatus()).toEqual(unverifiedClaims);
    });

    it('throws the invalid-session code for a revoked session (401 Invalid authentication)', async () => {
      mocks.fetchSessionStatus.mockResolvedValue(REVOKED_RESULT);

      await expect(readSessionStatus()).rejects.toMatchObject({
        code: 'auth/invalid-session-cookie',
      });
    });

    it.each([
      ['a 503', { success: false, error: 'Request failed', status: 503 }],
      ['an unreachable backend', OUTAGE_RESULT],
      [
        'a 401 that is not about the session (misconfigured internal key)',
        {
          success: false,
          error: 'Unauthorized',
          status: 401,
        },
      ],
    ])(
      'throws a plain error without a session code for %s, so the user is not logged out',
      async (_l, result) => {
        mocks.fetchSessionStatus.mockResolvedValue(result);

        const error = await readSessionStatus().catch((e) => e);

        expect(error).toBeInstanceOf(Error);
        expect(error.message).toBe('Session status check failed');
        expect(error.code).toBeUndefined();
      }
    );
  });

  describe('no session cookie', () => {
    it('is unauthenticated even with a forged email-verified cookie', async () => {
      mocks.cookieJar.clear();
      mocks.cookieJar.set('email-verified', 'true');

      expect(await getVerifiedSessionClaims()).toBeNull();
      expect(await getVerifiedUserId()).toBeNull();
      expect(mocks.fetchSessionStatus).not.toHaveBeenCalled();
    });
  });

  describe('backend lookup (GET /v1/me)', () => {
    it.each([
      ['401', { success: false, error: 'Unauthorized', status: 401 }],
      ['404 (no user)', { success: false, error: 'Not found', status: 404 }],
      ['500', { success: false, error: 'Request failed', status: 500 }],
      ['unreachable', { success: false, error: 'Backend unavailable' }],
    ])('fails closed on backend %s', async (_label, result) => {
      mocks.fetchProfile.mockResolvedValue(result);

      expect(await getVerifiedUserId()).toBeNull();
      expect(mocks.loggerError).toHaveBeenCalledTimes(1);
    });

    it('fails closed when the call throws', async () => {
      mocks.fetchProfile.mockRejectedValue(new Error('boom'));

      expect(await getVerifiedUserId()).toBeNull();
    });

    it('fails closed on an empty or malformed id', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: true, data: { id: '' } });
      expect(await getVerifiedUserId()).toBeNull();

      mocks.fetchProfile.mockResolvedValue({ success: true, data: {} });
      expect(await getVerifiedUserId()).toBeNull();

      mocks.fetchProfile.mockResolvedValue({ success: true, data: { id: 42 } });
      expect(await getVerifiedUserId()).toBeNull();
    });

    it('returns the backend id, never the Firebase uid', async () => {
      mocks.fetchProfile.mockResolvedValue({ success: true, data: { id: 'backend-id-9' } });

      expect(await getVerifiedUserId()).toBe('backend-id-9');
      expect(mocks.fetchProfile).toHaveBeenCalledTimes(1);
    });

    it('does not look up the profile for a revoked session', async () => {
      mocks.fetchSessionStatus.mockResolvedValue(REVOKED_RESULT);

      expect(await getVerifiedUserId()).toBeNull();
      expect(mocks.fetchProfile).not.toHaveBeenCalled();
    });
  });

  it('logs an unverified rejection as a warning without leaking the cookie', async () => {
    mocks.fetchSessionStatus.mockResolvedValue(ok(unverifiedClaims));

    await getVerifiedUserId();

    expect(mocks.loggerWarn).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(mocks.loggerWarn.mock.calls)).not.toContain('session-cookie');
  });

  it('classifies only its own error as email-not-verified', () => {
    expect(isEmailNotVerifiedError(REVOKED)).toBe(false);
    expect(isEmailNotVerifiedError(null)).toBe(false);
    expect(isEmailNotVerifiedError('auth/email-not-verified')).toBe(false);
  });
});
