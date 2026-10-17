/**
 * KAN-240: the one message the auth server actions return when the sign-in service itself is down or
 * failing (backend unreachable, 5xx, not configured), as opposed to refusing the user's token. It lives
 * outside the `"use server"` actions file because that file may only export async functions. It is display
 * text only: the outage is signalled by `data.serviceUnavailable` on the action response (KAN-241), never
 * by matching this text, and it never carries backend detail.
 */
export const SIGN_IN_SERVICE_UNAVAILABLE_ERROR = 'Sign-in service unavailable';

/** Typed outage marker on an auth action response, the same pattern as `data.signInRequired`. */
export interface ServiceUnavailableData {
  serviceUnavailable: true;
}

/** The part of a failed auth action response the forms read. */
export interface AuthFailureResult {
  error?: string;
  data?: { serviceUnavailable?: boolean } | null;
}

/** True when an auth action response carries the typed outage flag. */
export function isServiceUnavailableResult(result: AuthFailureResult): boolean {
  return result.data?.serviceUnavailable === true;
}

/**
 * True when a failed backend call means the service is unavailable rather than the request being refused:
 * no HTTP status (unreachable) or a 5xx. 4xx statuses (401, 403, 409, 422, 429) are the backend's answer and
 * keep their own handling.
 */
export function isServiceUnavailable(status: number | undefined): boolean {
  return status === undefined || status >= 500;
}

/** Set on the error `getBackendClient` throws when `BACKEND_API_URL` or `BACKEND_INTERNAL_KEY` is missing. */
export const BACKEND_NOT_CONFIGURED_CODE = 'backend/not-configured';

const OUTAGE_ERROR_CODES = new Set([
  BACKEND_NOT_CONFIGURED_CODE,
  // Firebase Admin / client network failures
  'app/network-error',
  'app/network-timeout',
  'auth/network-request-failed',
  // Node socket errors
  'ECONNREFUSED',
  'ECONNRESET',
  'ENOTFOUND',
  'ETIMEDOUT',
  'EAI_AGAIN',
]);

function errorCode(value: unknown): unknown {
  return typeof value === 'object' && value !== null
    ? (value as { code?: unknown }).code
    : undefined;
}

/**
 * True when a THROWN error means the sign-in service cannot be used (missing backend settings, or a
 * network failure from Firebase Admin or the fetch layer) rather than an unexpected bug. The error text is
 * never used: only its code, or the code of its `cause`.
 */
export function isServiceUnavailableError(error: unknown): boolean {
  const code = errorCode(error);
  const causeCode = errorCode(
    typeof error === 'object' && error !== null ? (error as { cause?: unknown }).cause : undefined
  );
  return (
    (typeof code === 'string' && OUTAGE_ERROR_CODES.has(code)) ||
    (typeof causeCode === 'string' && OUTAGE_ERROR_CODES.has(causeCode))
  );
}
