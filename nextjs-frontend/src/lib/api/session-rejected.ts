/**
 * True when a failed API result means "this browser session is no longer usable": the backend rejected it
 * (401 "Invalid authentication", e.g. revoked) or has no platform user for it (404, a session minted before
 * the API cutover). The caller clears the session so the user signs in again, which syncs the platform user.
 *
 * A 401 "Unauthorized" is a misconfigured internal key and an unreachable backend has no status; neither
 * is a reason to log anyone out.
 */
/** The backend's 401 body for a missing, invalid or revoked session (`app/api/auth.py`). */
export const INVALID_AUTHENTICATION_MESSAGE = 'Invalid authentication';

export function isSessionRejected(result: { status?: number; error: string }): boolean {
  return (
    result.status === 404 ||
    (result.status === 401 && result.error === INVALID_AUTHENTICATION_MESSAGE)
  );
}
