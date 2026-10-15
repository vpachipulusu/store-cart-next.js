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
import {
  isFieldName,
  onboardingSchema,
  resumeSchema,
  type FieldErrors,
  type OnboardingSubmission,
} from '@/lib/onboarding/schema';
import { isStoreId } from '@/lib/stores/selection';

/**
 * Merchant onboarding actions (KAN-60). Each one needs a verified session; ownership is decided by the backend
 * from the session cookie, so no organisation or user id comes from the browser. Backend error text is never
 * forwarded: the user sees fixed messages, and an expired session is the `unauthorized` code, which the client
 * turns into text.
 */

export type CreateStoreResponse =
  | { success: true; data: { storeId: string }; error?: undefined; fieldErrors?: undefined }
  | {
      success: false;
      data?: undefined;
      error?: string;
      fieldErrors?: FieldErrors;
      code?: 'unauthorized';
      /** The business exists but the store was not created; the form switches to resume mode. */
      organizationCreated?: true;
    };

export type StoreStatusResponse =
  | { success: true; data: { status: StoreStatus; name: string }; error?: undefined }
  | { success: false; data?: undefined; error?: string; notFound?: true; code?: 'unauthorized' };

const SLUG_TAKEN_MESSAGE = 'That address is already taken. Choose another.';
const INVALID_ADDRESS_MESSAGE = 'That address cannot be used. Choose another.';
const LIMIT_MESSAGE = 'Your plan does not allow another store.';
const ALREADY_ONBOARDED_MESSAGE = 'You already have a store. Open your dashboard.';
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
  issues: ReadonlyArray<{ path: ReadonlyArray<PropertyKey>; message: string }>
): FieldErrors {
  const fieldErrors: FieldErrors = {};
  for (const issue of issues) {
    const key = issue.path[0];
    if (isFieldName(key) && !fieldErrors[key]) fieldErrors[key] = issue.message;
  }
  return fieldErrors;
}

export async function createStoreAction(
  submission: OnboardingSubmission
): Promise<CreateStoreResponse> {
  if (!(await hasVerifiedSession())) return { success: false, code: 'unauthorized' };

  const parsed =
    submission?.mode === 'resume'
      ? resumeSchema.safeParse(submission)
      : onboardingSchema.safeParse(submission);
  if (!parsed.success) return { success: false, fieldErrors: fieldErrorsFrom(parsed.error.issues) };

  try {
    const result = await createOrganizationWithStore(parsed.data);
    if (result.success) {
      revalidatePath('/dashboard', 'layout');
      return { success: true, data: { storeId: result.storeId } };
    }
    const createdWithoutStore = result.stage === 'store' && result.organizationId !== undefined;
    const resumable = createdWithoutStore ? ({ organizationCreated: true } as const) : {};
    const slugField = result.stage === 'store' ? 'storeSlug' : 'organizationSlug';

    switch (result.reason) {
      case 'slug_taken':
        return {
          success: false,
          fieldErrors: { [slugField]: SLUG_TAKEN_MESSAGE },
          ...resumable,
        };
      case 'invalid':
        return {
          success: false,
          fieldErrors: { [slugField]: INVALID_ADDRESS_MESSAGE },
          ...resumable,
        };
      case 'unauthorized':
        return { success: false, code: 'unauthorized' };
      case 'limit':
        return { success: false, error: LIMIT_MESSAGE, ...resumable };
      case 'already_onboarded':
        return { success: false, error: ALREADY_ONBOARDED_MESSAGE };
      default:
        logger.error('Onboarding failed', { reason: result.reason, stage: result.stage });
        return {
          success: false,
          error: createdWithoutStore ? PARTIAL_ERROR : GENERIC_ERROR,
          ...resumable,
        };
    }
  } catch (error) {
    logger.error('Onboarding error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, error: GENERIC_ERROR };
  }
}

/** Polled by the status screen. The backend authorizes the read; a store the caller cannot open is "not found". */
export async function getStoreStatusAction(storeId: string): Promise<StoreStatusResponse> {
  if (!(await hasVerifiedSession())) return { success: false, code: 'unauthorized' };
  if (!isStoreId(storeId)) return { success: false, notFound: true };

  try {
    const result = await fetchStoreStatus(storeId);
    if (result.success) {
      return { success: true, data: { status: result.data.status, name: result.data.name } };
    }
    if (result.reason === 'not_found') return { success: false, notFound: true };
    return { success: false, error: STATUS_ERROR };
  } catch (error) {
    logger.error('Store status error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, error: STATUS_ERROR };
  }
}
