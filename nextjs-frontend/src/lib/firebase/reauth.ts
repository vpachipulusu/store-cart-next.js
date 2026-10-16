import {
  EmailAuthProvider,
  GithubAuthProvider,
  GoogleAuthProvider,
  reauthenticateWithCredential,
  reauthenticateWithPopup,
  signInWithEmailAndPassword,
  type User,
} from 'firebase/auth';
import { verifyTokenAction } from '@/app/actions/auth-actions';
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

/**
 * After a password change (KAN-208): Firebase has revoked this browser's refresh tokens and the server session
 * cookie. Signs in again with the NEW password to get a fresh ID token, then mints a new session cookie from it.
 * Resolves false when any step fails, so the caller can send the user to /login. Neither the password nor the
 * token is stored or logged here.
 */
export async function restoreSessionWithNewPassword(newPassword: string): Promise<boolean> {
  const email = auth.currentUser?.email;
  if (!email) return false;
  try {
    const credential = await signInWithEmailAndPassword(auth, email, newPassword);
    const idToken = await credential.user.getIdToken(true);
    const result = await verifyTokenAction(idToken);
    return result.success;
  } catch {
    return false;
  }
}
