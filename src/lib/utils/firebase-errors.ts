/**
 * Convert Firebase error codes to user-friendly messages
 */
export function getFirebaseErrorMessage(error: any): string {
  // Handle if error is a string
  if (typeof error === 'string') {
    error = { message: error, code: extractErrorCode(error) };
  }

  const code = error?.code || extractErrorCode(error?.message || '');

  // Map Firebase error codes to user-friendly messages
  const errorMessages: Record<string, string> = {
    // Auth errors
    'auth/email-already-in-use': 'This email is already registered. Please sign in instead.',
    'auth/invalid-email': 'Please enter a valid email address.',
    'auth/operation-not-allowed':
      'This sign-in method is not enabled. Please contact support or try a different sign-in method.',
    'auth/weak-password': 'Password is too weak. Please use a stronger password.',
    'auth/user-disabled': 'This account has been disabled. Please contact support.',
    'auth/user-not-found': 'No account found with this email. Please check your email or sign up.',
    'auth/wrong-password': 'Incorrect password. Please try again.',
    'auth/invalid-credential': 'Invalid email or password. Please try again.',
    'auth/too-many-requests':
      'Too many failed attempts. Please try again later or reset your password.',
    'auth/network-request-failed': 'Network error. Please check your connection and try again.',
    'auth/popup-closed-by-user': 'Sign-in was cancelled.',
    'auth/cancelled-popup-request': 'Sign-in was cancelled.',
    'auth/popup-blocked': 'Pop-up was blocked by your browser. Please allow pop-ups and try again.',
    'auth/unauthorized-domain': 'This domain is not authorized. Please contact support.',
    'auth/invalid-action-code': 'This link is invalid or has expired. Please try again.',
    'auth/expired-action-code': 'This link has expired. Please request a new one.',
    'auth/invalid-verification-code': 'Invalid verification code. Please try again.',
    'auth/missing-verification-code': 'Please enter the verification code.',
    'auth/account-exists-with-different-credential':
      'An account already exists with this email using a different sign-in method.',
    'auth/credential-already-in-use': 'This credential is already associated with another account.',
    'auth/requires-recent-login': 'Please sign in again to complete this action.',

    // Configuration errors
    'auth/configuration-not-found':
      'This sign-in method is not configured. Please contact support.',
    'auth/unauthorized-continue-uri': 'The redirect URL is not authorized. Please contact support.',
    'auth/invalid-continue-uri': 'Invalid redirect URL. Please contact support.',

    // Multi-factor errors
    'auth/multi-factor-auth-required': 'Additional verification is required to sign in.',
    'auth/maximum-second-factor-count-exceeded': 'Maximum number of verification methods reached.',
    'auth/unsupported-first-factor': 'This account requires additional verification.',

    // Token errors
    'auth/invalid-id-token': 'Your session has expired. Please sign in again.',
    'auth/id-token-expired': 'Your session has expired. Please sign in again.',
    'auth/id-token-revoked': 'Your session has been revoked. Please sign in again.',
    'auth/session-cookie-expired': 'Your session has expired. Please sign in again.',
    'auth/session-cookie-revoked': 'Your session has been revoked. Please sign in again.',

    // Quota errors
    'auth/quota-exceeded': 'Too many requests. Please try again later.',
    'auth/admin-restricted-operation': 'This operation is restricted. Please contact support.',

    // Password reset
    'auth/invalid-password': 'Invalid password. Password must be at least 6 characters.',
    'auth/missing-password': 'Please enter a password.',
  };

  // Return user-friendly message if available, otherwise a generic message
  if (code && errorMessages[code]) {
    return errorMessages[code];
  }

  // For unknown errors, return a generic message without exposing technical details
  return 'An error occurred. Please try again or contact support if the problem persists.';
}

/**
 * Extract error code from Firebase error message
 * Firebase errors often come as "Firebase: Error (auth/error-code)." or "auth/error-code"
 */
function extractErrorCode(message: string): string | null {
  if (!message) return null;

  // Check if message already contains the error code
  const match = message.match(/\(([^)]+)\)/);
  if (match && match[1]) {
    return match[1];
  }

  // Check if message is just the error code
  if (message.startsWith('auth/')) {
    return message;
  }

  return null;
}
