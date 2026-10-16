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
export const CURRENCY_REQUEST_TIMEOUT_MS = 3_000;

let cached: { code: string; expiresAt: number } | null = null;
let inflight: Promise<string> | null = null;

async function loadCurrency(): Promise<string> {
  // Public route: no session cookie. The timeout keeps a backend outage from hanging page renders.
  const result = await callBackend(
    (client) => readCurrency({ client, signal: AbortSignal.timeout(CURRENCY_REQUEST_TIMEOUT_MS) }),
    { withSession: false }
  );
  const code: unknown = result.success ? result.data?.currency : undefined;
  if (typeof code !== 'string' || code.trim() === '') {
    throw new Error(CURRENCY_LOOKUP_FAILED_MESSAGE);
  }
  cached = { code, expiresAt: Date.now() + CURRENCY_CACHE_TTL_MS };
  return code;
}

/** Concurrent callers on a cold or expired cache share one backend request. */
export function fetchPlatformCurrency(): Promise<string> {
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.code);
  inflight ??= loadCurrency().finally(() => {
    inflight = null;
  });
  return inflight;
}
