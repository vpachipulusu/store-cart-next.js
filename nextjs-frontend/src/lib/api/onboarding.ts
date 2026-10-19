import 'server-only';

import { callBackend, type ApiResult } from './server';
import {
  createOrganization,
  createStore,
  listOrganizations,
  readStore,
  retryStoreProvisioning,
  type OrganizationData,
  type StoreStatus,
} from './generated';

/** The business fields are needed only when no owned, store-less organisation exists to reuse. */
export type CreateOnboardingInput = {
  storeName: string;
  storeSlug: string;
  organizationName?: string;
  organizationSlug?: string;
};

/**
 * Server-only calls behind merchant onboarding (KAN-60): create the first organisation and store, and read a
 * store's provisioning status. The browser never supplies an organisation id; the backend authorizes every call
 * from the session cookie, and a store the caller cannot open reads as "not found".
 */

export type { StoreStatus };

/** A user owns at most 10 organisations (MAX_OWNED_ORGANIZATIONS), so one page of the API's maximum size suffices. */
const ORGANIZATIONS_PAGE_SIZE = 100;

export type OnboardingFailureReason =
  | 'slug_taken'
  | 'invalid'
  | 'limit'
  | 'unauthorized'
  | 'already_onboarded'
  | 'unavailable';

export type CreateOnboardingResult =
  | { success: true; storeId: string; organizationId: string; resumed: boolean }
  | {
      success: false;
      reason: OnboardingFailureReason;
      stage: 'organization' | 'store';
      /** Set when the organisation exists but the store was not created; a retry reuses it. */
      organizationId?: string;
    };

export type OnboardingState =
  | { kind: 'new' }
  | { kind: 'resume'; organizationName: string }
  | { kind: 'done' };

export type StoreStatusResult =
  | { success: true; data: { id: string; name: string; status: StoreStatus } }
  | { success: false; reason: 'not_found' | 'unavailable' };

type Failure = Extract<ApiResult<unknown>, { success: false }>;

/**
 * Maps a failed create call. 409 is either a taken slug or a limit (plan store limit, organisation cap); the
 * backend says "Slug is already taken" for the former. 403 is a role or plan refusal. The backend text is never
 * forwarded.
 */
function reasonFor(failure: Failure): OnboardingFailureReason {
  switch (failure.status) {
    case 409:
      return /slug/i.test(failure.error) ? 'slug_taken' : 'limit';
    case 403:
      return 'limit';
    case 422:
      return 'invalid';
    case 401:
      return 'unauthorized';
    default:
      return 'unavailable';
  }
}

async function listOwnOrganizations(): Promise<ApiResult<OrganizationData[]>> {
  return callBackend((client) =>
    listOrganizations({ client, query: { limit: ORGANIZATIONS_PAGE_SIZE } })
  );
}

const hasAnyStore = (organizations: ReadonlyArray<OrganizationData>) =>
  organizations.some(
    (organization) => organization.stores.length > 0 || organization.stores_truncated
  );

/** An organisation the user owns that has no store yet: the leftover of a half-finished onboarding. */
const findResumable = (organizations: ReadonlyArray<OrganizationData>) =>
  organizations.find(
    (organization) => organization.role === 'OWNER' && organization.stores.length === 0
  );

export async function fetchOnboardingState(): Promise<ApiResult<OnboardingState>> {
  const result = await listOwnOrganizations();
  if (!result.success) return result;
  if (hasAnyStore(result.data)) return { success: true, data: { kind: 'done' } };
  const resumable = findResumable(result.data);
  return {
    success: true,
    data: resumable ? { kind: 'resume', organizationName: resumable.name } : { kind: 'new' },
  };
}

/**
 * Creates the user's organisation and first store. If an owned organisation without a store already exists (a
 * previous attempt created it but the store step failed) it is reused, so a retry never creates a second one.
 */
export async function createOrganizationWithStore(
  input: CreateOnboardingInput
): Promise<CreateOnboardingResult> {
  const existing = await listOwnOrganizations();
  if (!existing.success) {
    return { success: false, reason: reasonFor(existing), stage: 'organization' };
  }
  if (hasAnyStore(existing.data)) {
    return { success: false, reason: 'already_onboarded', stage: 'organization' };
  }

  const resumable = findResumable(existing.data);
  let organizationId = resumable?.id;
  if (!organizationId) {
    if (!input.organizationName || !input.organizationSlug) {
      return { success: false, reason: 'invalid', stage: 'organization' };
    }
    const organizationName = input.organizationName;
    const organizationSlug = input.organizationSlug;
    const created = await callBackend((client) =>
      createOrganization({
        client,
        body: { name: organizationName, slug: organizationSlug },
      })
    );
    if (!created.success) {
      return { success: false, reason: reasonFor(created), stage: 'organization' };
    }
    organizationId = created.data.id;
  }

  const owningOrganizationId = organizationId;
  const store = await callBackend((client) =>
    createStore({
      client,
      path: { organization_id: owningOrganizationId },
      body: { name: input.storeName, slug: input.storeSlug },
    })
  );
  if (!store.success) {
    return {
      success: false,
      reason: reasonFor(store),
      stage: 'store',
      organizationId: owningOrganizationId,
    };
  }
  return {
    success: true,
    storeId: store.data.id,
    organizationId: owningOrganizationId,
    resumed: resumable !== undefined,
  };
}

export type NewStoreFailureReason =
  | 'slug_taken'
  | 'invalid'
  | 'limit'
  | 'forbidden'
  | 'not_found'
  | 'unauthorized'
  | 'unavailable';

export type CreateStoreInOrganizationResult =
  | { success: true; storeId: string; name: string; status: StoreStatus }
  | { success: false; reason: NewStoreFailureReason; limitMessage?: string };

/** The backend's 409 text for a taken store slug (`http_error` in app/api/v1/organizations.py). */
const SLUG_TAKEN_ERROR = 'Slug is already taken';

/**
 * The backend's plan store limit text (`store_limit_message` in app/services/plan_limits.py, KAN-84), e.g. "The
 * Free plan allows 1 store. Upgrade your plan to add more." Only text of exactly this shape is shown to the user;
 * anything else falls back to a fixed message. Change both together.
 */
const STORE_LIMIT_PATTERN =
  /^The [A-Za-z][A-Za-z ]{0,39} plan allows \d{1,6} stores?\. Upgrade your plan to add more\.$/;
/** Looser store-limit wording (the same message reworded): still an upgrade prompt, but with the fixed text. */
const STORE_LIMIT_FALLBACK_PATTERN = /\bplan allows \d+ stores?\b/i;

function newStoreFailure(failure: Failure): CreateStoreInOrganizationResult {
  switch (failure.status) {
    case 409:
      if (failure.error === SLUG_TAKEN_ERROR) return { success: false, reason: 'slug_taken' };
      if (STORE_LIMIT_PATTERN.test(failure.error)) {
        return { success: false, reason: 'limit', limitMessage: failure.error };
      }
      // Any other conflict (the organisation cap, a concurrent change) is not a plan upgrade issue.
      return {
        success: false,
        reason: STORE_LIMIT_FALLBACK_PATTERN.test(failure.error) ? 'limit' : 'unavailable',
      };
    case 403:
      return { success: false, reason: 'forbidden' };
    case 404:
      return { success: false, reason: 'not_found' };
    case 422:
      return { success: false, reason: 'invalid' };
    case 401:
      return { success: false, reason: 'unauthorized' };
    default:
      return { success: false, reason: 'unavailable' };
  }
}

/**
 * Creates another store in one of the caller's organisations ("New store", KAN-254). The caller passes an
 * organisation id it took from the server-validated store selection, never from the browser, and the backend
 * authorizes the role and enforces the plan's store limit.
 */
export async function createStoreInOrganization(
  organizationId: string,
  input: { storeName: string; storeSlug: string }
): Promise<CreateStoreInOrganizationResult> {
  const result = await callBackend((client) =>
    createStore({
      client,
      path: { organization_id: organizationId },
      body: { name: input.storeName, slug: input.storeSlug },
    })
  );
  if (!result.success) return newStoreFailure(result);
  return {
    success: true,
    storeId: result.data.id,
    name: result.data.name,
    status: result.data.status,
  };
}

/** The store's provisioning status. 403 and 404 both read as "not found" so another tenant's id reveals nothing. */
export async function fetchStoreStatus(storeId: string): Promise<StoreStatusResult> {
  const result = await callBackend((client) => readStore({ client, path: { store_id: storeId } }));
  if (result.success) {
    return {
      success: true,
      data: { id: result.data.id, name: result.data.name, status: result.data.status },
    };
  }
  if (result.status === 403 || result.status === 404) {
    return { success: false, reason: 'not_found' };
  }
  return { success: false, reason: 'unavailable' };
}

export type RetryFailureReason =
  | 'limit'
  | 'not_failed'
  | 'rate_limited'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'unavailable';

export type RetryProvisioningResult =
  | { success: true; attempt: number; maxAttempts: number }
  | { success: false; reason: RetryFailureReason };

/**
 * The backend's exact 409 text at the attempt cap (`RETRY_LIMIT_MESSAGE` in app/services/admin_stores.py,
 * shared with the admin re-run); any other 409 is "not FAILED". Change both together.
 */
export const RETRY_LIMIT_MESSAGE = 'Provisioning retry limit reached';

function retryReasonFor(failure: Failure): RetryFailureReason {
  switch (failure.status) {
    case 409:
      return failure.error === RETRY_LIMIT_MESSAGE ? 'limit' : 'not_failed';
    case 401:
      return 'unauthorized';
    case 403:
      return 'forbidden';
    case 404:
      return 'not_found';
    case 429:
      return 'rate_limited';
    default:
      return 'unavailable';
  }
}

/**
 * Asks the backend to re-run provisioning of a FAILED store (KAN-242). Only an owner or admin of the store's
 * organisation may; the cap and rate limit are the backend's. Backend text is mapped to a fixed reason, never
 * forwarded.
 */
export async function requestProvisioningRetry(storeId: string): Promise<RetryProvisioningResult> {
  const result = await callBackend((client) =>
    retryStoreProvisioning({ client, path: { store_id: storeId } })
  );
  if (result.success) {
    return { success: true, attempt: result.data.attempt, maxAttempts: result.data.max_attempts };
  }
  return { success: false, reason: retryReasonFor(result) };
}
