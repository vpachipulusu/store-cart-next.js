import 'server-only';

import { callBackend } from './server';
import { readStorefront } from './generated';
import { isValidStoreSlug } from '@/lib/storefront/host';

/**
 * Server-only public storefront lookup (KAN-64, backend KAN-65: `GET /v1/storefront/{slug}`).
 * The backend returns the store only when it is ACTIVE; unknown, malformed, reserved and non-active slugs all
 * produce the same 404. `callBackend` forwards the internal key and, on Vercel, the visitor's IP as
 * `X-Client-IP`, so the backend's per-IP rate limit does not put every visitor in one bucket.
 */

export interface PublicStorefront {
  readonly name: string;
  readonly slug: string;
}

export const STOREFRONT_LOOKUP_FAILED_MESSAGE = 'Storefront lookup failed';

/**
 * The public store for `slug`, or null when there is no live store. Any other failure (backend down, rate
 * limited, bad key) throws, so an outage is an error page and never a cached "store does not exist".
 */
export async function fetchStorefront(slug: string): Promise<PublicStorefront | null> {
  if (!isValidStoreSlug(slug)) return null;
  const result = await callBackend((client) => readStorefront({ client, path: { slug } }));
  if (result.success) {
    // Only the public fields are passed on, whatever else the backend might add later.
    return { name: result.data.name, slug: result.data.slug };
  }
  if (result.status === 404) return null;
  throw new Error(STOREFRONT_LOOKUP_FAILED_MESSAGE);
}
