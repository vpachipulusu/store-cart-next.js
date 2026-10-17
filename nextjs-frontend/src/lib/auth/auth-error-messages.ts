/**
 * KAN-240: the one message the auth server actions return when the sign-in service itself is down or
 * failing (backend unreachable, 5xx), as opposed to refusing the user's token. It lives outside the
 * `"use server"` actions file because that file may only export async functions. The sign-in forms match
 * on this exact text (see `classifyAuthError`), and it never carries backend detail.
 */
export const SIGN_IN_SERVICE_UNAVAILABLE_ERROR = 'Sign-in service unavailable';

/**
 * True when a failed backend call means the service is unavailable rather than the request being refused:
 * no HTTP status (unreachable) or a 5xx. 4xx statuses (401, 403, 409, 422, 429) are the backend's answer and
 * keep their own handling.
 */
export function isServiceUnavailable(status: number | undefined): boolean {
  return status === undefined || status >= 500;
}
