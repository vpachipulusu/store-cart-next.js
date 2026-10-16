// @vitest-environment node
/**
 * KAN-180: account deletion and 2FA disable take a fresh Firebase ID token from the browser's
 * re-authentication dialog. The token is forwarded to the API once and is never logged or returned.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const ID_TOKEN = 'FRESH-ID-TOKEN-eyJhbGciOi';

const mocks = vi.hoisted(() => ({
  removeBackendAccount: vi.fn(),
  disableBackendTotp: vi.fn(),
  cookieDelete: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: vi.fn(), delete: mocks.cookieDelete }),
}));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedSessionClaims: vi.fn(),
  isEmailNotVerifiedError: () => false,
}));
vi.mock('@/lib/api/account', () => ({
  removeBackendAccount: mocks.removeBackendAccount,
  disableBackendTotp: mocks.disableBackendTotp,
}));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import { deleteAccountAction, disableTwoFactorAction } from '@/app/actions/user-actions';

const OWNER_MESSAGE = 'Transfer organization ownership before deleting your account';
const ok = <T>(data: T) => ({ success: true as const, data });
const failure = (status?: number, error = 'backend detail') => ({
  success: false as const,
  error,
  status,
});

function everythingLogged(): string {
  return JSON.stringify(mocks.logError.mock.calls);
}

describe('deleteAccountAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.removeBackendAccount.mockResolvedValue(ok({ success: true }));
  });

  it('forwards the fresh token and clears the session cookie on success', async () => {
    const result = await deleteAccountAction(ID_TOKEN);

    expect(result.success).toBe(true);
    expect(mocks.removeBackendAccount).toHaveBeenCalledWith(ID_TOKEN);
    expect(mocks.cookieDelete).toHaveBeenCalledWith('session');
    expect(JSON.stringify(result)).not.toContain(ID_TOKEN);
  });

  it('shows the API 409 message to organisation owners and keeps the session', async () => {
    mocks.removeBackendAccount.mockResolvedValue(failure(409, OWNER_MESSAGE));

    const result = await deleteAccountAction(ID_TOKEN);

    expect(result).toEqual({ success: false, error: OWNER_MESSAGE });
    expect(mocks.cookieDelete).not.toHaveBeenCalled();
  });

  it.each([401, 403])('asks for re-authentication on a %i', async (status) => {
    mocks.removeBackendAccount.mockResolvedValue(failure(status));

    expect(await deleteAccountAction(ID_TOKEN)).toEqual({
      success: false,
      error: 'Re-authentication required',
    });
    expect(mocks.cookieDelete).not.toHaveBeenCalled();
  });

  it('answers generically on a server error and never logs the token', async () => {
    mocks.removeBackendAccount.mockResolvedValue(failure(500, 'SECRET internal detail'));

    const result = await deleteAccountAction(ID_TOKEN);

    expect(result).toEqual({ success: false, error: 'Failed to delete account' });
    expect(everythingLogged()).not.toContain(ID_TOKEN);
  });

  it('answers generically when the call throws, without logging the token', async () => {
    mocks.removeBackendAccount.mockRejectedValue(new Error('boom'));

    expect(await deleteAccountAction(ID_TOKEN)).toEqual({
      success: false,
      error: 'Failed to delete account',
    });
    expect(everythingLogged()).not.toContain(ID_TOKEN);
  });

  it('rejects an empty token without calling the API', async () => {
    const result = await deleteAccountAction('');

    expect(result).toEqual({ success: false, error: 'Re-authentication required' });
    expect(mocks.removeBackendAccount).not.toHaveBeenCalled();
  });
});

describe('disableTwoFactorAction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.disableBackendTotp.mockResolvedValue(ok({ success: true }));
  });

  it('forwards the token and the code to the API', async () => {
    const result = await disableTwoFactorAction(ID_TOKEN, '123456');

    expect(result.success).toBe(true);
    expect(mocks.disableBackendTotp).toHaveBeenCalledWith(ID_TOKEN, '123456');
  });

  it.each(['', '12345', '1234567', 'abcdef', '12 456'])(
    'rejects the malformed code %j before calling the API',
    async (code) => {
      const result = await disableTwoFactorAction(ID_TOKEN, code);

      expect(result.success).toBe(false);
      expect(mocks.disableBackendTotp).not.toHaveBeenCalled();
    }
  );

  it('reports an invalid authenticator code on a 400', async () => {
    mocks.disableBackendTotp.mockResolvedValue(failure(400));

    expect(await disableTwoFactorAction(ID_TOKEN, '123456')).toEqual({
      success: false,
      error: 'Invalid authenticator code',
    });
  });

  it('asks for re-authentication on a 401', async () => {
    mocks.disableBackendTotp.mockResolvedValue(failure(401));

    expect(await disableTwoFactorAction(ID_TOKEN, '123456')).toEqual({
      success: false,
      error: 'Re-authentication required',
    });
  });

  it('answers generically on a server error and never logs the token', async () => {
    mocks.disableBackendTotp.mockResolvedValue(failure(500, 'SECRET internal detail'));

    const result = await disableTwoFactorAction(ID_TOKEN, '123456');

    expect(result).toEqual({ success: false, error: 'Failed to disable two-factor' });
    expect(everythingLogged()).not.toContain(ID_TOKEN);
  });
});
