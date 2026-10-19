'use server';

import { logger } from '@/lib/logger';
import { getVerifiedUserId } from '@/lib/auth/verified-session';
import { buildConnectReturnUrls } from '@/lib/stripe/return-urls';
import {
  NO_CONNECT_ORGANIZATION_MESSAGE,
  fetchConnectStatus,
  startConnectOnboarding,
} from '@/lib/api/connect';

/**
 * Stripe Connect server actions (KAN-67). Onboarding itself is Stripe-hosted: these only read the capability flags
 * the Connect webhook keeps in sync and ask the backend for a one-time onboarding link. Messages shown to the
 * browser are curated here; no backend or Stripe text reaches it.
 *
 * A failure carries a `kind` so the panel can tell "nothing to do here" (no organisation, not allowed: an
 * informational note without Retry) from a signed-out session and from an outage (Retry).
 */

export type ConnectStatus = {
  hasAccount: boolean;
  chargesEnabled: boolean;
  payoutsEnabled: boolean;
  detailsSubmitted: boolean;
};

export type ConnectFailureKind = 'no_organization' | 'forbidden' | 'session' | 'retry';

type ConnectActionResponse<T> =
  | { success: true; data: T }
  | { success: false; error: string; kind: ConnectFailureKind };

const MESSAGES = {
  session: 'Your session has expired. Please sign in again.',
  noOrganization: 'Create a store first. Payments are set up for your store’s organisation.',
  notFound: 'We could not find the payment settings for this store’s organisation.',
  forbidden: 'Only an organisation owner or admin can set up payments.',
  unavailable: 'We could not reach the payment provider. Please try again in a few minutes.',
  notConfigured: 'Payments are not available right now. Please try again later.',
  loadFailed: 'We could not load your payment status.',
  startFailed: 'We could not start payment setup. Please try again.',
} as const;

function failure(
  error: string,
  kind: ConnectFailureKind
): { success: false; error: string; kind: ConnectFailureKind } {
  return { success: false, error, kind };
}

function classify(
  error: string,
  status: number | undefined,
  fallback: string
): { success: false; error: string; kind: ConnectFailureKind } {
  if (error === NO_CONNECT_ORGANIZATION_MESSAGE) {
    return failure(MESSAGES.noOrganization, 'no_organization');
  }
  switch (status) {
    case 401:
      return failure(MESSAGES.session, 'session');
    case 403:
      return failure(MESSAGES.forbidden, 'forbidden');
    case 404:
      return failure(MESSAGES.notFound, 'no_organization');
    case 502:
      return failure(MESSAGES.unavailable, 'retry');
    case 503:
      return failure(MESSAGES.notConfigured, 'retry');
    default:
      return failure(fallback, 'retry');
  }
}

function errorClass(error: unknown): string {
  return error instanceof Error ? error.constructor.name : typeof error;
}

export async function getConnectStatusAction(): Promise<ConnectActionResponse<ConnectStatus>> {
  try {
    if (!(await getVerifiedUserId())) return failure(MESSAGES.session, 'session');

    const result = await fetchConnectStatus();
    if (!result.success) {
      logger.error('Get Connect status failed:', { status: result.status });
      return classify(result.error, result.status, MESSAGES.loadFailed);
    }
    return {
      success: true,
      data: {
        hasAccount: result.data.has_account,
        chargesEnabled: result.data.charges_enabled,
        payoutsEnabled: result.data.payouts_enabled,
        detailsSubmitted: result.data.details_submitted,
      },
    };
  } catch (error: unknown) {
    logger.error('Get Connect status error:', { cause: errorClass(error) });
    return failure(MESSAGES.loadFailed, 'retry');
  }
}

/** Returns the Stripe-hosted onboarding URL; the browser then navigates to it. */
export async function startConnectOnboardingAction(): Promise<
  ConnectActionResponse<{ url: string }>
> {
  try {
    if (!(await getVerifiedUserId())) return failure(MESSAGES.session, 'session');

    const { returnUrl, refreshUrl } = buildConnectReturnUrls();
    const result = await startConnectOnboarding(returnUrl, refreshUrl);
    if (!result.success) {
      logger.error('Start Connect onboarding failed:', { status: result.status });
      return classify(result.error, result.status, MESSAGES.startFailed);
    }
    return { success: true, data: { url: result.data.url } };
  } catch (error: unknown) {
    logger.error('Start Connect onboarding error:', { cause: errorClass(error) });
    return failure(MESSAGES.startFailed, 'retry');
  }
}
