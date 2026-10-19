/**
 * Store setup (provisioning) states shared by the admin store list and the merchant dashboard (KAN-255). Pure and
 * safe to import from client code.
 */

/** Mirrors STUCK_AFTER in fastapi_backend/app/services/admin_stores.py: the backend re-runs a quiet store only after this long. */
export const STUCK_AFTER_MINUTES = 15;
const STUCK_AFTER_MS = STUCK_AFTER_MINUTES * 60_000;

/**
 * A PROVISIONING store with no change for longer than the backend threshold: its job gave up silently, and the
 * admin re-run (and merchant retry) will fail it and start a new run. A malformed date never offers a re-run.
 */
export function isStalledProvisioning(status: string, updatedAt: string, now: number): boolean {
  if (status !== 'PROVISIONING') return false;
  const updated = Date.parse(updatedAt);
  return Number.isFinite(updated) && now - updated > STUCK_AFTER_MS;
}

/** Merchant "Retry setup" outcomes, shared by the onboarding status page and the dashboard setup state. */
export const RETRY_LIMIT_MESSAGE = 'We have already tried the maximum number of times.';
export const RETRY_MESSAGES = {
  rate_limited: 'Too many attempts. Wait a few minutes and try again.',
  forbidden: 'Only an owner or admin of this business can retry the setup.',
  unavailable: 'We could not retry the setup. Please try again.',
} as const;

export type SetupStatus = 'PROVISIONING' | 'FAILED';

/** The store has no usable database yet, so store-scoped pages show the setup state instead of loading data. */
export function isStoreInSetup(status: string): status is SetupStatus {
  return status === 'PROVISIONING' || status === 'FAILED';
}
