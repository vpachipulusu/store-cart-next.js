import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
  GoogleAuthProvider,
  GithubAuthProvider,
  signInWithPopup,
  sendPasswordResetEmail,
  sendEmailVerification,
  User,
} from 'firebase/auth';
import { auth } from './client';
import { getFirebaseErrorMessage } from '@/lib/utils/firebase-errors';

/**
 * Sign in with email and password
 */
export async function signInWithEmail(email: string, password: string) {
  try {
    const userCredential = await signInWithEmailAndPassword(auth, email, password);
    const idToken = await userCredential.user.getIdToken();
    return { user: userCredential.user, idToken, error: null };
  } catch (error: any) {
    return { user: null, idToken: null, error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Sign up with email and password
 */
export async function signUpWithEmail(email: string, password: string) {
  try {
    const userCredential = await createUserWithEmailAndPassword(auth, email, password);
    const idToken = await userCredential.user.getIdToken();

    // Send email verification
    await sendEmailVerification(userCredential.user);

    return { user: userCredential.user, idToken, error: null };
  } catch (error: any) {
    return { user: null, idToken: null, error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Sign in with Google
 */
export async function signInWithGoogle() {
  try {
    const provider = new GoogleAuthProvider();
    const userCredential = await signInWithPopup(auth, provider);
    const idToken = await userCredential.user.getIdToken();
    return { user: userCredential.user, idToken, error: null };
  } catch (error: any) {
    return { user: null, idToken: null, error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Sign in with GitHub
 */
export async function signInWithGitHub() {
  try {
    const provider = new GithubAuthProvider();
    const userCredential = await signInWithPopup(auth, provider);
    const idToken = await userCredential.user.getIdToken();
    return { user: userCredential.user, idToken, error: null };
  } catch (error: any) {
    return { user: null, idToken: null, error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Sign out
 */
export async function signOut() {
  try {
    await firebaseSignOut(auth);
    return { error: null };
  } catch (error: any) {
    return { error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Send password reset email
 */
export async function resetPassword(email: string) {
  try {
    await sendPasswordResetEmail(auth, email);
    return { error: null };
  } catch (error: any) {
    return { error: getFirebaseErrorMessage(error) };
  }
}

/**
 * Get current user's ID token
 */
export async function getCurrentUserToken(): Promise<string | null> {
  const user = auth.currentUser;
  if (!user) return null;
  return await user.getIdToken();
}

/**
 * Resend email verification
 */
export async function resendVerificationEmail(user: User) {
  try {
    await sendEmailVerification(user);
    return { error: null };
  } catch (error: any) {
    return { error: error.message };
  }
}
