import 'server-only';

import { isIP } from 'node:net';
import { cookies, headers } from 'next/headers';
import { BACKEND_NOT_CONFIGURED_CODE } from '@/lib/auth/auth-error-messages';
import { createClient, createConfig, type Client } from './generated/client';

/**
 * Server-only entry point to the FastAPI backend (ADR-003, ADR-008, ADR-011).
 *
 * Call generated SDK functions through `callBackend`, which builds the client from
 * BACKEND_API_URL, forwards the Firebase `session` cookie to the backend in the
 * `X-Session-Token` header, and folds every outcome into the `{ success, ... }` envelope.
 * The browser never calls the backend, and nothing here reaches a client bundle.
 *
 * BACKEND_INTERNAL_KEY is server-only and forwarded as X-Internal-Key (ADR-003).
 * Public health endpoints remain callable without it; auth endpoints reject missing keys.
 */

export const SESSION_COOKIE_NAME = 'session';
export const SESSION_HEADER = 'X-Session-Token';
export const INTERNAL_KEY_HEADER = 'X-Internal-Key';

export const BACKEND_UNAVAILABLE_MESSAGE = 'Backend unavailable';
export const BACKEND_ERROR_MESSAGE = 'Request failed';

/** `status` is the backend HTTP status when the backend answered (absent when it was unreachable). */
export type ApiResult<T> =
  | { success: true; data: T }
  | { success: false; error: string; status?: number };

type SdkResult<TData> = { data?: TData; error?: unknown; response?: Response };

/** Generated success envelopes are unwrapped; plain success bodies retain their type. */
export type BackendData<T> = T extends { data: infer TPayload; success?: true } ? TPayload : T;

/** A missing backend setting. Sign-in maps it to a service-unavailable result; the text is for server logs only. */
function notConfigured(variable: string): Error {
  return Object.assign(new Error(`${variable} is not set`), { code: BACKEND_NOT_CONFIGURED_CODE });
}

function getBackendUrl(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) {
    throw notConfigured('BACKEND_API_URL');
  }
  return url.replace(/\/+$/, '');
}

/** `withSession: false` leaves the caller's session cookie out, for public internal-key-only routes. */
export interface BackendOptions {
  withSession?: boolean;
  /** Throw when BACKEND_INTERNAL_KEY is missing; for routes the backend rejects without it (sign-in). */
  requireInternalKey?: boolean;
}

/** A fresh client per call, so one request's session can never leak into another. */
export async function getBackendClient({
  withSession = true,
  requireInternalKey = false,
}: BackendOptions = {}): Promise<Client> {
  const sessionToken = withSession ? (await cookies()).get(SESSION_COOKIE_NAME)?.value : undefined;
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  if (requireInternalKey && !internalKey) {
    throw notConfigured('BACKEND_INTERNAL_KEY');
  }
  // Caller headers are trusted only at Vercel's boundary, never raw X-Forwarded-For.
  const forwardedIp =
    internalKey && process.env.VERCEL === '1'
      ? (await headers()).get('x-vercel-forwarded-for')?.trim()
      : undefined;
  return createClient(
    createConfig({
      baseUrl: getBackendUrl(),
      cache: 'no-store',
      headers: {
        ...(sessionToken ? { [SESSION_HEADER]: sessionToken } : {}),
        ...(internalKey ? { [INTERNAL_KEY_HEADER]: internalKey } : {}),
        ...(forwardedIp && isIP(forwardedIp) ? { 'X-Client-IP': forwardedIp } : {}),
      },
    })
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** The backend's error envelope is `{ success: false, error: string }` (KAN-31). */
function errorMessage(error: unknown): string {
  if (isRecord(error) && error.success === false && typeof error.error === 'string') {
    return error.error;
  }
  return BACKEND_ERROR_MESSAGE;
}

/** Unwrap `{ success: true, data }` bodies; pass other success bodies through. */
function unwrap<T>(body: unknown): BackendData<T> {
  if (isRecord(body) && body.success === true && 'data' in body) {
    return body.data as BackendData<T>;
  }
  return body as BackendData<T>;
}

export async function callBackend<TData>(
  call: (client: Client) => Promise<SdkResult<TData>>,
  options: BackendOptions = {}
): Promise<ApiResult<BackendData<TData>>> {
  const client = await getBackendClient(options);
  let result: SdkResult<TData>;
  try {
    result = await call(client);
  } catch {
    return { success: false, error: BACKEND_UNAVAILABLE_MESSAGE };
  }

  // The generated client reports a failed fetch (no response) through `error`, not by throwing.
  if (result.error !== undefined && !result.response) {
    return { success: false, error: BACKEND_UNAVAILABLE_MESSAGE };
  }
  if (result.error !== undefined || (result.response && !result.response.ok)) {
    return { success: false, error: errorMessage(result.error), status: result.response?.status };
  }
  return { success: true, data: unwrap<TData>(result.data) };
}
