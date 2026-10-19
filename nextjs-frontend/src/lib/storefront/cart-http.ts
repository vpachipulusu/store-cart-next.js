import 'server-only';

import { headers } from 'next/headers';
import { z } from 'zod';
import type { ApiResult } from '@/lib/api/server';
import type { Cart } from '@/lib/api/cart';
import { STORE_SLUG_HEADER } from '@/lib/storefront/host';

/**
 * Shared plumbing for the storefront cart route handlers (KAN-76): the store guard, a same-origin check for writes,
 * body validation and the JSON response. The pages of a storefront call these handlers on their own host; the
 * browser never calls FastAPI.
 */

export const MAX_CART_QUANTITY = 99;
const MAX_VARIANT_ID_LENGTH = 100;
const MAX_BODY_CHARS = 2_000;

/** The backend id alphabet; anything else (dots, slashes, encoded dot-segments) never reaches the backend path. */
export const variantIdSchema = z
  .string()
  .regex(new RegExp(`^[A-Za-z0-9_-]{1,${MAX_VARIANT_ID_LENGTH}}$`));
const quantitySchema = z.number().int().min(1).max(MAX_CART_QUANTITY);
export const addItemSchema = z.object({ variantId: variantIdSchema, quantity: quantitySchema });
export const quantityBodySchema = z.object({ quantity: quantitySchema });

const JSON_HEADERS = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } as const;

export function jsonResponse(body: unknown, status: number, extra: HeadersInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...extra },
  });
}

export function failure(error: string, status: number): Response {
  return jsonResponse({ success: false, error }, status);
}

/**
 * Null when the request may continue. Like the storefront page, a request that did not come through the proxy
 * rewrite for this same slug is a 404. A write whose `Origin` is another host is refused. This is the protection
 * against another store's page: sibling store subdomains are the same site, so the SameSite=Lax cookie is still sent
 * on their requests. `Origin: null` (sandboxed frames) is refused too; a request with no Origin (not a browser
 * write) has no cart cookie of a shopper to abuse.
 */
export async function guardStoreRequest(
  request: Request,
  slug: string,
  options: { write: boolean }
): Promise<Response | null> {
  if ((await headers()).get(STORE_SLUG_HEADER) !== slug) return failure('Store not found', 404);
  if (!options.write) return null;
  const origin = request.headers.get('origin');
  if (origin !== null) {
    let originHost: string | null = null;
    try {
      originHost = new URL(origin).host;
    } catch {
      originHost = null;
    }
    if (originHost !== request.headers.get('host')) return failure('Request not allowed', 403);
  }
  return null;
}

/** The parsed JSON body, or a 4xx response when it is not JSON, too large or does not match the schema. */
export async function parseBody<T>(
  request: Request,
  schema: z.ZodType<T>
): Promise<{ ok: true; value: T } | { ok: false; response: Response }> {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
    return { ok: false, response: failure('Send JSON', 415) };
  }
  const declared = Number(request.headers.get('content-length') ?? 0);
  if (declared > MAX_BODY_CHARS) return { ok: false, response: failure('Request too large', 413) };
  const text = await request.text();
  if (text.length > MAX_BODY_CHARS)
    return { ok: false, response: failure('Request too large', 413) };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, response: failure('Invalid request', 422) };
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) return { ok: false, response: failure('Invalid request', 422) };
  return { ok: true, value: parsed.data };
}

/** The cart as JSON, or the failure with its status (an unknown status becomes 502). */
export function cartResponse(result: ApiResult<Cart>): Response {
  if (result.success) return jsonResponse({ success: true, data: result.data }, 200);
  const status = result.status;
  if (status === 404 || status === 409 || status === 429 || status === 503) {
    return failure(result.error, status);
  }
  return failure(result.error, status === undefined ? 503 : 502);
}
