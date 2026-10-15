'use server';

import { revalidatePath } from 'next/cache';
import {
  createOrganizationWithStore,
  fetchStoreStatus,
  type StoreStatus,
} from '@/lib/api/onboarding';
import { getVerifiedSessionClaims, isEmailNotVerifiedError } from '@/lib/auth/verified-session';
import { isSessionVerificationError } from '@/lib/auth/session-errors';
import { logger } from '@/lib/logger';
import { onboardingSchema, type OnboardingInput } from '@/lib/onboarding/schema';
import { isStoreId } from '@/lib/stores/selection';

/**
 * Merchant onboarding actions (KAN-60). Each one needs a verified session; ownership is decided by the backend
 * from the session cookie, so no organisation or user id comes from the browser. Backend error text is never
 * forwarded: the user sees fixed messages.
 */

type FieldErrors = Partial<Record<keyof OnboardingInput, string>>;

export type CreateStoreResponse =
  | { success: true; data: { storeId: string }; error?: undefined; fieldErrors?: undefined }
  | { success: false; data?: undefined; error?: string; fieldErrors?: FieldErrors };

export type StoreStatusResponse =
  | {
      success: true;
      data: { status: StoreStatus; name: string };
      error?: undefined;
      notFound?: undefined;
    }
  | { success: false; data?: undefined; error: string; notFound?: true };

const UNAUTHORIZED = 'Unauthorized';
const SLUG_TAKEN_MESSAGE = 'That address is already taken. Choose another.';
const INVALID_ADDRESS_MESSAGE = 'That address cannot be used. Choose another.';
const GENERIC_ERROR = 'We could not set up your store. Please try again.';
const PARTIAL_ERROR =
  'Your business was created but the store was not. Submit again to finish setting it up.';
const STATUS_ERROR = 'Could not check your store. Please try again.';

async function hasVerifiedSession(): Promise<boolean> {
  try {
    return (await getVerifiedSessionClaims()) !== null;
  } catch (error) {
    // Invalid, revoked and unverified sessions are all "not signed in"; anything else is an outage worth a log.
    if (!isEmailNotVerifiedError(error) && !isSessionVerificationError(error)) {
      logger.error('Onboarding session check failed', {
        errorName: error instanceof Error ? error.name : typeof error,
      });
    }
    return false;
  }
}

function fieldErrorsFrom(
  issues: ReadonlyArray<{ path: ReadonlyArray<string | number>; message: string }>
) {
  const fieldErrors: FieldErrors = {};
  for (const issue of issues) {
    const key = issue.path[0] as keyof OnboardingInput | undefined;
    if (key && !fieldErrors[key]) fieldErrors[key] = issue.message;
  }
  return fieldErrors;
}

export async function createStoreAction(input: OnboardingInput): Promise<CreateStoreResponse> {
  if (!(await hasVerifiedSession())) return { success: false, error: UNAUTHORIZED };

  const parsed = onboardingSchema.safeParse(input);
  if (!parsed.success) return { success: false, fieldErrors: fieldErrorsFrom(parsed.error.issues) };

  try {
    const result = await createOrganizationWithStore(parsed.data);
    if (result.success) {
      revalidatePath('/dashboard', 'layout');
      return { success: true, data: { storeId: result.storeId } };
    }
    if (result.reason === 'slug_taken') {
      const field = result.stage === 'store' ? 'storeSlug' : 'organizationSlug';
      return { success: false, fieldErrors: { [field]: SLUG_TAKEN_MESSAGE } };
    }
    if (result.reason === 'invalid') {
      const field = result.stage === 'store' ? 'storeSlug' : 'organizationSlug';
      return { success: false, fieldErrors: { [field]: INVALID_ADDRESS_MESSAGE } };
    }
    if (result.reason === 'unauthorized') return { success: false, error: UNAUTHORIZED };
    if (result.reason === 'limit') {
      return { success: false, error: 'Your plan does not allow another store.' };
    }
    if (result.reason === 'already_onboarded') {
      return { success: false, error: 'You already have a store. Open your dashboard.' };
    }
    logger.error('Onboarding failed', { reason: result.reason, stage: result.stage });
    if (result.stage === 'store' && result.organizationId) {
      return { success: false, error: PARTIAL_ERROR };
    }
    return { success: false, error: GENERIC_ERROR };
  } catch (error) {
    logger.error('Onboarding error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, error: GENERIC_ERROR };
  }
}

/** Polled by the status screen. The backend authorizes the read; a store the caller cannot open is "not found". */
export async function getStoreStatusAction(storeId: string): Promise<StoreStatusResponse> {
  if (!(await hasVerifiedSession())) return { success: false, error: UNAUTHORIZED };
  if (!isStoreId(storeId)) return { success: false, error: 'Store not found', notFound: true };

  try {
    const result = await fetchStoreStatus(storeId);
    if (result.success) {
      return { success: true, data: { status: result.data.status, name: result.data.name } };
    }
    if (result.reason === 'not_found') {
      return { success: false, error: 'Store not found', notFound: true };
    }
    return { success: false, error: STATUS_ERROR };
  } catch (error) {
    logger.error('Store status error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, error: STATUS_ERROR };
  }
}
