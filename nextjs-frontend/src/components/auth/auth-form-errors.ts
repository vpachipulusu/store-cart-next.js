import { getFirebaseErrorMessage } from '@/lib/utils/firebase-errors';

/**
 * KAN-227: turns the text returned by the Firebase helpers into the alert copy of plan sections 6.4
 * and 7. The helpers only return text, so the text is matched back to its code through
 * `getFirebaseErrorMessage` itself; reworded messages stay in step. Wording never says whether an
 * account exists, and raw server text is never shown.
 */
export type AuthFlow = 'sign-in' | 'sign-up' | 'reset';

export type AuthErrorKind =
  | 'credentials'
  | 'account-missing'
  | 'network'
  | 'rate-limit'
  | 'suspended'
  | 'weak-password'
  | 'unknown';

export interface AuthFormError {
  kind: AuthErrorKind;
  title: string;
  message: string;
}

const KIND_BY_CODE: Record<string, AuthErrorKind> = {
  'auth/invalid-credential': 'credentials',
  'auth/wrong-password': 'credentials',
  'auth/invalid-email': 'credentials',
  'auth/email-already-in-use': 'credentials',
  'auth/account-exists-with-different-credential': 'credentials',
  'auth/user-not-found': 'account-missing',
  'auth/network-request-failed': 'network',
  'auth/too-many-requests': 'rate-limit',
  'auth/quota-exceeded': 'rate-limit',
  'auth/user-disabled': 'suspended',
  'auth/weak-password': 'weak-password',
};

const KIND_BY_MESSAGE = new Map<string, AuthErrorKind>(
  Object.entries(KIND_BY_CODE).map(([code, kind]) => [getFirebaseErrorMessage({ code }), kind])
);

const TITLE_BY_FLOW: Record<AuthFlow, string> = {
  'sign-in': 'We could not sign you in',
  'sign-up': 'We could not create your account',
  reset: 'We could not send the reset link',
};

const CREDENTIALS_MESSAGE: Record<AuthFlow, string> = {
  'sign-in':
    'That email and password do not match. Check them and try again, or reset your password.',
  'sign-up':
    'If you already have an account, sign in or reset your password. Otherwise check your details and try again.',
  reset: 'Check the email address and try again.',
};

export const NETWORK_ERROR: AuthFormError = {
  kind: 'network',
  title: 'We could not reach StoreCart',
  message: 'Check your connection and try again.',
};

export function classifyAuthError(
  message: string | null | undefined,
  flow: AuthFlow
): AuthFormError {
  const kind = (message && KIND_BY_MESSAGE.get(message)) || 'unknown';

  switch (kind) {
    case 'credentials':
    case 'account-missing':
      return { kind, title: TITLE_BY_FLOW[flow], message: CREDENTIALS_MESSAGE[flow] };
    case 'network':
      return NETWORK_ERROR;
    case 'rate-limit':
      return {
        kind,
        title: 'Too many attempts',
        message:
          flow === 'reset'
            ? 'Wait a few minutes before trying again.'
            : 'Wait a few minutes before trying again, or reset your password.',
      };
    case 'suspended':
      return {
        kind,
        title: 'This account is suspended',
        message: 'If you think this is a mistake, we can help.',
      };
    case 'weak-password':
      return {
        kind,
        title: TITLE_BY_FLOW[flow],
        message: 'Choose a stronger password and try again.',
      };
    default:
      return {
        kind: 'unknown',
        title: TITLE_BY_FLOW[flow],
        message: 'Something went wrong on our side. Try again in a moment.',
      };
  }
}
