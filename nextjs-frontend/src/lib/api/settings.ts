import 'server-only';

import { callBackend } from './server';
import { readCurrency } from './generated';

/**
 * Server-only platform settings read (KAN-205: `GET /v1/settings/currency`, internal key, no session).
 * Exposes only the currency code; any failure throws so the caller picks its own fallback.
 *
 * The backend's per-IP rate limit sees every server-side call as one client, so reads are cached in memory
 * per server instance. `unstable_cache` cannot be used because `callBackend` reads cookies. Only successes
 * are cached, so an outage is never remembered; a currency change shows within `CURRENCY_CACHE_TTL_MS`.
 */

export const CURRENCY_LOOKUP_FAILED_MESSAGE = 'Currency lookup failed';
export const CURRENCY_CACHE_TTL_MS = 60_000;

let cached: { code: string; expiresAt: number } | null = null;

export async function fetchPlatformCurrency(): Promise<string> {
  const now = Date.now();
  if (cached && cached.expiresAt > now) return cached.code;

  const result = await callBackend((client) => readCurrency({ client }));
  if (!result.success) throw new Error(CURRENCY_LOOKUP_FAILED_MESSAGE);
  cached = { code: result.data.currency, expiresAt: now + CURRENCY_CACHE_TTL_MS };
  return cached.code;
}
