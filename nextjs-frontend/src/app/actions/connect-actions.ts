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
 */

export type ConnectStatus = {
  hasAccount: boolean;
  chargesEnabled: boolean;
  payoutsEnabled: boolean;
  detailsSubmitted: boolean;
};

type ConnectActionResponse<T> = { success: true; data: T } | { success: false; error: string };

const MESSAGES = {
  unauthorized: 'Your session has expired. Please sign in again.',
  noOrganization: 'Create a store first. Payments are set up for your organisation.',
  forbidden: 'Only an organisation owner or admin can set up payments.',
  unavailable: 'We could not reach the payment provider. Please try again in a few minutes.',
  notConfigured: 'Payments are not available right now. Please try again later.',
  loadFailed: 'We could not load your payment status.',
  startFailed: 'We could not start payment setup. Please try again.',
} as const;

function messageFor(error: string, status: number | undefined, fallback: string): string {
  if (error === NO_CONNECT_ORGANIZATION_MESSAGE) return MESSAGES.noOrganization;
  switch (status) {
    case 401:
      return MESSAGES.unauthorized;
    case 403:
    case 404:
      return MESSAGES.forbidden;
    case 502:
      return MESSAGES.unavailable;
    case 503:
      return MESSAGES.notConfigured;
    default:
      return fallback;
  }
}

function errorClass(error: unknown): string {
  return error instanceof Error ? error.constructor.name : typeof error;
}

export async function getConnectStatusAction(): Promise<ConnectActionResponse<ConnectStatus>> {
  try {
    if (!(await getVerifiedUserId())) return { success: false, error: MESSAGES.unauthorized };

    const result = await fetchConnectStatus();
    if (!result.success) {
      logger.error('Get Connect status failed:', { status: result.status });
      return {
        success: false,
        error: messageFor(result.error, result.status, MESSAGES.loadFailed),
      };
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
    return { success: false, error: MESSAGES.loadFailed };
  }
}

/** Returns the Stripe-hosted onboarding URL; the browser then navigates to it. */
export async function startConnectOnboardingAction(): Promise<
  ConnectActionResponse<{ url: string }>
> {
  try {
    if (!(await getVerifiedUserId())) return { success: false, error: MESSAGES.unauthorized };

    const { returnUrl, refreshUrl } = buildConnectReturnUrls();
    const result = await startConnectOnboarding(returnUrl, refreshUrl);
    if (!result.success) {
      logger.error('Start Connect onboarding failed:', { status: result.status });
      return {
        success: false,
        error: messageFor(result.error, result.status, MESSAGES.startFailed),
      };
    }
    return { success: true, data: { url: result.data.url } };
  } catch (error: unknown) {
    logger.error('Start Connect onboarding error:', { cause: errorClass(error) });
    return { success: false, error: MESSAGES.startFailed };
  }
}
