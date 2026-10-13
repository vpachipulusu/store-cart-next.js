import { logger } from '@/lib/logger';

/**
 * firebase-admin error codes that mean "this session cannot be trusted" when verifying a session
 * cookie. Anything else (database outage, network failure, quota, bug) is NOT a session problem and
 * must not log the user out. Codes overlap those in `utils/firebase-errors.ts`, which maps client-side
 * codes to user-facing text and has no server-side classification.
 */
const SESSION_VERIFICATION_ERROR_CODES: ReadonlySet<string> = new Set([
  'auth/session-cookie-expired',
  'auth/session-cookie-revoked',
  'auth/id-token-revoked',
  'auth/user-disabled',
  'auth/user-not-found',
  'auth/invalid-session-cookie',
  'auth/argument-error',
]);

export function isSessionVerificationError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  const { code } = error as { code?: unknown };
  return typeof code === 'string' && SESSION_VERIFICATION_ERROR_CODES.has(code);
}

/**
 * Logs an unexpected (non-session) failure from a server-rendered route. Records the route, error
 * name/message and the user id when known. Never pass cookies or tokens here.
 */
export function logRouteError(route: string, error: unknown, userId?: string): void {
  logger.error('Unexpected error while rendering route', {
    route,
    errorName: error instanceof Error ? error.name : typeof error,
    message: error instanceof Error ? error.message : String(error),
    ...(userId ? { userId } : {}),
  });
}
