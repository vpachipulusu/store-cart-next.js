import {
  EmailAuthProvider,
  GithubAuthProvider,
  GoogleAuthProvider,
  reauthenticateWithCredential,
  reauthenticateWithPopup,
  type User,
} from 'firebase/auth';
import { auth } from './client';
import { getFirebaseErrorMessage } from '@/lib/utils/firebase-errors';

/** How the signed-in user proves who they are again: their password, or the provider's popup. */
export type ReauthMethod = 'password' | 'google' | 'github';

export type ReauthResult = { idToken: string; error: null } | { idToken: null; error: string };

/** Picks the method from the user's linked providers; password wins when the account has one. */
export function reauthMethodFor(user: Pick<User, 'providerData'> | null): ReauthMethod | null {
  const ids = user?.providerData.map((provider) => provider.providerId) ?? [];
  if (ids.includes('password')) return 'password';
  if (ids.includes('google.com')) return 'google';
  if (ids.includes('github.com')) return 'github';
  return null;
}

/**
 * Re-authenticates the current Firebase user and returns a fresh ID token (KAN-180). The backend only
 * accepts tokens minted in the last five minutes. The token is returned to the caller to hand to a server
 * action; it is not stored or logged here, and neither is the password.
 */
export async function reauthenticate(
  method: ReauthMethod,
  password?: string
): Promise<ReauthResult> {
  const user = auth.currentUser;
  if (!user) return { idToken: null, error: 'You are signed out. Sign in again.' };
  try {
    if (method === 'password') {
      if (!user.email || !password) return { idToken: null, error: 'Enter your password' };
      await reauthenticateWithCredential(user, EmailAuthProvider.credential(user.email, password));
    } else {
      await reauthenticateWithPopup(
        user,
        method === 'google' ? new GoogleAuthProvider() : new GithubAuthProvider()
      );
    }
    return { idToken: await user.getIdToken(true), error: null };
  } catch (error: unknown) {
    return { idToken: null, error: getFirebaseErrorMessage(error) };
  }
}
