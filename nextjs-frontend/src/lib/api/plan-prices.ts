import 'server-only';

import { logger } from '@/lib/logger';
import { callBackend } from './server';
import { readPlanPrices } from './generated';

/**
 * Server-only plan price read (KAN-208: `GET /v1/settings/plan-prices`, internal key, no session). The backend
 * asks Stripe for each configured price and answers per price: an amount in minor units, or null when that price
 * is not configured, not readable or has no amount. One failing price never hides the others.
 *
 * Prices are shown in major units. A null price is shown as 0, as the old Stripe read did for a missing amount,
 * and a failed read falls back to all zeros. Reads are cached in memory per server instance for an hour
 * (`unstable_cache` cannot be used because `callBackend` reads request headers). A failure is remembered only
 * briefly, so an outage does not blank the prices for an hour, and a backend that is down cannot be hammered.
 */

export interface TierPrices {
  monthly: number;
  yearly: number;
}

export interface PlanPrices {
  pro: TierPrices;
  enterprise: TierPrices;
}

export const PLAN_PRICES_CACHE_TTL_MS = 60 * 60 * 1000;
export const PLAN_PRICES_FAILURE_TTL_MS = 60 * 1000;
export const PLAN_PRICES_REQUEST_TIMEOUT_MS = 5_000;

const MINOR_UNITS_PER_MAJOR = 100;

export const FALLBACK_PLAN_PRICES: PlanPrices = {
  pro: { monthly: 0, yearly: 0 },
  enterprise: { monthly: 0, yearly: 0 },
};

let cached: { prices: PlanPrices; expiresAt: number } | null = null;
let inflight: Promise<PlanPrices> | null = null;

function toMajorUnits(minor: number | null | undefined): number {
  return typeof minor === 'number' && Number.isFinite(minor) && minor >= 0
    ? minor / MINOR_UNITS_PER_MAJOR
    : 0;
}

async function loadPlanPrices(): Promise<PlanPrices> {
  const result = await callBackend(
    (client) =>
      readPlanPrices({ client, signal: AbortSignal.timeout(PLAN_PRICES_REQUEST_TIMEOUT_MS) }),
    { withSession: false }
  );
  if (!result.success) {
    logger.warn('Plan prices read failed, using fallback prices', {
      error: result.error,
      status: result.status,
    });
    cached = { prices: FALLBACK_PLAN_PRICES, expiresAt: Date.now() + PLAN_PRICES_FAILURE_TTL_MS };
    return FALLBACK_PLAN_PRICES;
  }
  const { pro, enterprise } = result.data;
  const prices: PlanPrices = {
    pro: { monthly: toMajorUnits(pro?.monthly), yearly: toMajorUnits(pro?.yearly) },
    enterprise: {
      monthly: toMajorUnits(enterprise?.monthly),
      yearly: toMajorUnits(enterprise?.yearly),
    },
  };
  cached = { prices, expiresAt: Date.now() + PLAN_PRICES_CACHE_TTL_MS };
  return prices;
}

/** Prices in major units, never throwing. Concurrent callers on a cold cache share one backend request. */
export function fetchPlanPrices(): Promise<PlanPrices> {
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.prices);
  inflight ??= loadPlanPrices()
    .catch((error: unknown) => {
      logger.error('Failed to fetch plan prices:', error);
      cached = { prices: FALLBACK_PLAN_PRICES, expiresAt: Date.now() + PLAN_PRICES_FAILURE_TTL_MS };
      return FALLBACK_PLAN_PRICES;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Test hook: forget the cached prices. */
export function resetPlanPricesCache(): void {
  cached = null;
  inflight = null;
}
