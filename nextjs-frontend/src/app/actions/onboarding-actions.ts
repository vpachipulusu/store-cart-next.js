'use server';

import { revalidatePath } from 'next/cache';
import {
  createOrganizationWithStore,
  createStoreInOrganization,
  fetchStoreStatus,
  requestProvisioningRetry,
  type RetryFailureReason,
  type StoreStatus,
} from '@/lib/api/onboarding';
import { getVerifiedSessionClaims, isEmailNotVerifiedError } from '@/lib/auth/verified-session';
import { isSessionVerificationError } from '@/lib/auth/session-errors';
import { logger } from '@/lib/logger';
import {
  isFieldName,
  NEW_STORE_FORBIDDEN_MESSAGE,
  NEW_STORE_LIMIT_MESSAGE,
  onboardingSchema,
  resumeSchema,
  type FieldErrors,
  type OnboardingSubmission,
  type ResumeInput,
} from '@/lib/onboarding/schema';
import { getCurrentStoreSelection } from '@/lib/stores/current';
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
const BUSINESS_MISSING_MESSAGE = 'We could not find your business. Reload the page and try again.';
const GENERIC_ERROR = 'We could not set up your store. Please try again.';
const PARTIAL_ERROR =
  'Your business was created but the store was not. Submit again to finish setting it up.';
const STATUS_ERROR = 'Could not check your store. Please try again.';
const NO_STORE_YET_MESSAGE = 'Set up your first store before adding another.';

type SessionState = 'ok' | 'unauthorized' | 'unavailable';

/** Signed-in, not signed-in (including revoked or unverified), or the check itself failed (an outage). */
async function checkSession(): Promise<SessionState> {
  try {
    return (await getVerifiedSessionClaims()) !== null ? 'ok' : 'unauthorized';
  } catch (error) {
    if (isEmailNotVerifiedError(error) || isSessionVerificationError(error)) return 'unauthorized';
    logger.error('Onboarding session check failed', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return 'unavailable';
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
  const session = await checkSession();
  if (session === 'unauthorized') return { success: false, code: 'unauthorized' };
  if (session === 'unavailable') return { success: false, error: GENERIC_ERROR };

  const parsed =
    submission?.mode === 'resume'
      ? resumeSchema.safeParse(submission)
      : onboardingSchema.safeParse(submission);
  if (!parsed.success) {
    const fieldErrors = fieldErrorsFrom(parsed.error.issues);
    return Object.keys(fieldErrors).length > 0
      ? { success: false, fieldErrors }
      : { success: false, error: GENERIC_ERROR };
  }

  try {
    const result = await createOrganizationWithStore(parsed.data);
    if (result.success) {
      revalidatePath('/dashboard', 'layout');
      return { success: true, data: { storeId: result.storeId } };
    }
    const createdWithoutStore = result.stage === 'store' && result.organizationId !== undefined;
    const resumable = createdWithoutStore ? ({ organizationCreated: true } as const) : {};
    const slugField = result.stage === 'store' ? 'storeSlug' : 'organizationSlug';

    // Resume mode shows no business fields, so a business-level problem needs a form-level message.
    if (
      submission.mode === 'resume' &&
      result.stage === 'organization' &&
      (result.reason === 'slug_taken' || result.reason === 'invalid')
    ) {
      return { success: false, error: BUSINESS_MISSING_MESSAGE };
    }

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

export type CreateAdditionalStoreResponse =
  | {
      success: true;
      data: { storeId: string; name: string; status: StoreStatus };
      error?: undefined;
      fieldErrors?: undefined;
    }
  | {
      success: false;
      data?: undefined;
      error?: string;
      fieldErrors?: FieldErrors;
      code?: 'unauthorized';
      /** The plan's store limit: `error` is the upgrade message, shown instead of the form. */
      limitReached?: true;
    };

/**
 * "New store" from the dashboard (KAN-254): another store in the organisation of the currently selected store.
 * The organisation comes from `getCurrentStoreSelection()` (the user's own stores, re-read from the backend), never
 * from the browser, and the backend authorizes the role and the plan limit. Input uses the onboarding rules.
 */
export async function createAdditionalStoreAction(
  input: ResumeInput
): Promise<CreateAdditionalStoreResponse> {
  const session = await checkSession();
  if (session === 'unauthorized') return { success: false, code: 'unauthorized' };
  if (session === 'unavailable') return { success: false, error: GENERIC_ERROR };

  const parsed = resumeSchema.safeParse(input);
  if (!parsed.success) {
    const fieldErrors = fieldErrorsFrom(parsed.error.issues);
    return Object.keys(fieldErrors).length > 0
      ? { success: false, fieldErrors }
      : { success: false, error: GENERIC_ERROR };
  }

  try {
    const selection = await getCurrentStoreSelection();
    if (!selection.available) return { success: false, error: GENERIC_ERROR };
    if (!selection.selected) return { success: false, error: NO_STORE_YET_MESSAGE };

    const result = await createStoreInOrganization(
      selection.selected.organizationId,
      parsed.data
    );
    if (result.success) {
      revalidatePath('/dashboard', 'layout');
      return {
        success: true,
        data: { storeId: result.storeId, name: result.name, status: result.status },
      };
    }
    switch (result.reason) {
      case 'slug_taken':
        return { success: false, fieldErrors: { storeSlug: SLUG_TAKEN_MESSAGE } };
      case 'invalid':
        return { success: false, fieldErrors: { storeSlug: INVALID_ADDRESS_MESSAGE } };
      case 'limit':
        return {
          success: false,
          limitReached: true,
          error: result.limitMessage ?? NEW_STORE_LIMIT_MESSAGE,
        };
      case 'forbidden':
        return { success: false, error: NEW_STORE_FORBIDDEN_MESSAGE };
      case 'unauthorized':
        return { success: false, code: 'unauthorized' };
      default:
        logger.error('New store failed', { reason: result.reason });
        return { success: false, error: GENERIC_ERROR };
    }
  } catch (error) {
    logger.error('New store error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, error: GENERIC_ERROR };
  }
}

/** Polled by the status screen. The backend authorizes the read; a store the caller cannot open is "not found". */
export async function getStoreStatusAction(storeId: string): Promise<StoreStatusResponse> {
  const session = await checkSession();
  if (session === 'unauthorized') return { success: false, code: 'unauthorized' };
  if (session === 'unavailable') return { success: false, error: STATUS_ERROR };
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

export type RetryProvisioningResponse =
  | { success: true; data: { attempt: number }; code?: undefined; reason?: undefined }
  | {
      success: false;
      data?: undefined;
      code?: 'unauthorized';
      reason?: Exclude<RetryFailureReason, 'unauthorized'>;
    };

/**
 * The merchant's "Retry setup" for a FAILED store (KAN-242). The backend decides who may (owner or admin), the
 * attempt cap and the rate limit; the client gets a fixed reason, never backend text.
 */
export async function retryProvisioningAction(storeId: string): Promise<RetryProvisioningResponse> {
  const session = await checkSession();
  if (session === 'unauthorized') return { success: false, code: 'unauthorized' };
  if (session === 'unavailable') return { success: false, reason: 'unavailable' };
  if (!isStoreId(storeId)) return { success: false, reason: 'not_found' };

  try {
    const result = await requestProvisioningRetry(storeId);
    if (result.success) return { success: true, data: { attempt: result.attempt } };
    if (result.reason === 'unauthorized') return { success: false, code: 'unauthorized' };
    return { success: false, reason: result.reason };
  } catch (error) {
    logger.error('Provisioning retry error', {
      errorName: error instanceof Error ? error.name : typeof error,
    });
    return { success: false, reason: 'unavailable' };
  }
}
