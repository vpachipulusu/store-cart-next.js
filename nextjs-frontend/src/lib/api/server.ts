import 'server-only';

import { cookies } from 'next/headers';
import { createClient, createConfig, type Client } from './generated/client';

/**
 * Server-only entry point to the FastAPI backend (ADR-003, ADR-008, ADR-011).
 *
 * Call generated SDK functions through `callBackend`, which builds the client from
 * BACKEND_API_URL, forwards the Firebase `session` cookie to the backend in the
 * `X-Session-Token` header, and folds every outcome into the `{ success, ... }` envelope.
 * The browser never calls the backend, and nothing here reaches a client bundle.
 *
 * The backend does not define an internal service key yet, so none is sent; add the
 * `X-Internal-Key` header here when it does (ADR-003).
 */

export const SESSION_COOKIE_NAME = 'session';
export const SESSION_HEADER = 'X-Session-Token';

export const BACKEND_UNAVAILABLE_MESSAGE = 'Backend unavailable';
export const BACKEND_ERROR_MESSAGE = 'Request failed';

export type ApiResult<T> = { success: true; data: T } | { success: false; error: string };

type SdkResult<TData> = { data?: TData; error?: unknown; response?: Response };

function getBackendUrl(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) {
    throw new Error('BACKEND_API_URL is not set');
  }
  return url.replace(/\/+$/, '');
}

/** A fresh client per call, so one request's session can never leak into another. */
export async function getBackendClient(): Promise<Client> {
  const sessionToken = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  return createClient(
    createConfig({
      baseUrl: getBackendUrl(),
      cache: 'no-store',
      headers: sessionToken ? { [SESSION_HEADER]: sessionToken } : undefined,
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
function unwrap<T>(body: unknown): T {
  if (isRecord(body) && body.success === true && 'data' in body) {
    return body.data as T;
  }
  return body as T;
}

export async function callBackend<TData>(
  call: (client: Client) => Promise<SdkResult<TData>>
): Promise<ApiResult<TData>> {
  const client = await getBackendClient();
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
    return { success: false, error: errorMessage(result.error) };
  }
  return { success: true, data: unwrap<TData>(result.data) };
}
