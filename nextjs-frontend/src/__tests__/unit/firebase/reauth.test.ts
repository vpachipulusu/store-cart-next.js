/**
 * KAN-180: the client re-authentication helper picks the right Firebase method and hands back a fresh ID
 * token without keeping the password.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  currentUser: null as null | {
    email: string | null;
    providerData: { providerId: string }[];
    getIdToken: ReturnType<typeof vi.fn>;
  },
  reauthenticateWithCredential: vi.fn(),
  reauthenticateWithPopup: vi.fn(),
  credential: vi.fn((email: string, password: string) => ({ email, password })),
  signInWithEmailAndPassword: vi.fn(),
  verifyTokenAction: vi.fn(),
}));

vi.mock('@/app/actions/auth-actions', () => ({ verifyTokenAction: mocks.verifyTokenAction }));

vi.mock('@/lib/firebase/client', () => ({
  auth: {
    get currentUser() {
      return mocks.currentUser;
    },
  },
}));
vi.mock('firebase/auth', () => ({
  EmailAuthProvider: { credential: mocks.credential },
  GoogleAuthProvider: class GoogleAuthProvider {},
  GithubAuthProvider: class GithubAuthProvider {},
  reauthenticateWithCredential: mocks.reauthenticateWithCredential,
  reauthenticateWithPopup: mocks.reauthenticateWithPopup,
  signInWithEmailAndPassword: mocks.signInWithEmailAndPassword,
}));
vi.mock('@/lib/utils/firebase-errors', () => ({
  getFirebaseErrorMessage: (error: { code?: string }) => `mapped:${error.code}`,
}));

import {
  reauthenticate,
  reauthMethodFor,
  restoreSessionWithNewPassword,
} from '@/lib/firebase/reauth';

function user(providerIds: string[], email: string | null = 'a@b.test') {
  return {
    email,
    providerData: providerIds.map((providerId) => ({ providerId })),
    getIdToken: vi.fn().mockResolvedValue('fresh-token'),
  };
}

describe('reauthMethodFor', () => {
  it.each([
    [['password'], 'password'],
    [['google.com', 'password'], 'password'],
    [['google.com'], 'google'],
    [['github.com'], 'github'],
    [['phone'], null],
  ])('maps providers %j to %s', (ids, expected) => {
    const providerData = ids.map((providerId) => ({ providerId }));

    expect(reauthMethodFor({ providerData } as never)).toBe(expected);
  });

  it('returns null when nobody is signed in', () => {
    expect(reauthMethodFor(null)).toBeNull();
  });
});

describe('reauthenticate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentUser = user(['password']);
    mocks.reauthenticateWithCredential.mockResolvedValue({});
    mocks.reauthenticateWithPopup.mockResolvedValue({});
  });

  it('re-enters the password and returns a force-refreshed ID token', async () => {
    const result = await reauthenticate('password', 'hunter22');

    expect(mocks.credential).toHaveBeenCalledWith('a@b.test', 'hunter22');
    expect(result).toEqual({ idToken: 'fresh-token', error: null });
    expect(mocks.currentUser?.getIdToken).toHaveBeenCalledWith(true);
  });

  it('uses the provider popup for OAuth users', async () => {
    mocks.currentUser = user(['google.com']);

    const result = await reauthenticate('google');

    expect(mocks.reauthenticateWithPopup).toHaveBeenCalledTimes(1);
    expect(mocks.reauthenticateWithCredential).not.toHaveBeenCalled();
    expect(result).toEqual({ idToken: 'fresh-token', error: null });
  });

  it('asks for the password when none was typed', async () => {
    const result = await reauthenticate('password', '');

    expect(result.idToken).toBeNull();
    expect(mocks.reauthenticateWithCredential).not.toHaveBeenCalled();
  });

  it('maps a Firebase failure to a message and returns no token', async () => {
    mocks.reauthenticateWithCredential.mockRejectedValue({ code: 'auth/wrong-password' });

    expect(await reauthenticate('password', 'wrong')).toEqual({
      idToken: null,
      error: 'mapped:auth/wrong-password',
    });
  });

  it('reports a signed-out user', async () => {
    mocks.currentUser = null;

    const result = await reauthenticate('password', 'x');

    expect(result.idToken).toBeNull();
  });
});

describe('restoreSessionWithNewPassword (KAN-208)', () => {
  beforeEach(() => {
    mocks.signInWithEmailAndPassword.mockReset();
    mocks.verifyTokenAction.mockReset();
  });

  it('signs in again with the new password and mints a new session from the fresh ID token', async () => {
    mocks.currentUser = user(['password']);
    const fresh = { getIdToken: vi.fn().mockResolvedValue('new-id-token') };
    mocks.signInWithEmailAndPassword.mockResolvedValue({ user: fresh });
    mocks.verifyTokenAction.mockResolvedValue({ success: true });

    await expect(restoreSessionWithNewPassword('new-pass-1')).resolves.toBe(true);

    expect(mocks.signInWithEmailAndPassword).toHaveBeenCalledWith(
      expect.anything(),
      'a@b.test',
      'new-pass-1'
    );
    expect(fresh.getIdToken).toHaveBeenCalledWith(true);
    expect(mocks.verifyTokenAction).toHaveBeenCalledWith('new-id-token');
  });

  it('resolves false when the server refuses the new session', async () => {
    mocks.currentUser = user(['password']);
    mocks.signInWithEmailAndPassword.mockResolvedValue({
      user: { getIdToken: vi.fn().mockResolvedValue('t') },
    });
    mocks.verifyTokenAction.mockResolvedValue({ success: false });

    await expect(restoreSessionWithNewPassword('new-pass-1')).resolves.toBe(false);
  });

  it('resolves false when the Firebase sign-in fails, and never calls the server', async () => {
    mocks.currentUser = user(['password']);
    mocks.signInWithEmailAndPassword.mockRejectedValue({ code: 'auth/wrong-password' });

    await expect(restoreSessionWithNewPassword('new-pass-1')).resolves.toBe(false);
    expect(mocks.verifyTokenAction).not.toHaveBeenCalled();
  });

  it('resolves false when nobody is signed in', async () => {
    mocks.currentUser = null;

    await expect(restoreSessionWithNewPassword('new-pass-1')).resolves.toBe(false);
    expect(mocks.signInWithEmailAndPassword).not.toHaveBeenCalled();
  });
});
