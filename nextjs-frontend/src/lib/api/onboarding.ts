import 'server-only';

import { callBackend, type ApiResult } from './server';
import {
  createOrganization,
  createStore,
  listOrganizations,
  readStore,
  type OrganizationData,
  type StoreStatus,
} from './generated';
import type { OnboardingInput } from '@/lib/onboarding/schema';

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
  input: OnboardingInput
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
    const created = await callBackend((client) =>
      createOrganization({
        client,
        body: { name: input.organizationName, slug: input.organizationSlug },
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
