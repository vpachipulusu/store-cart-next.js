import 'server-only';

import { callBackend, type ApiResult } from './server';
import {
  listOrganizations,
  listOrganizationStores,
  type OrganizationData,
  type StoreData,
} from './generated';
import type { MerchantStore } from '@/lib/stores/selection';

/**
 * Server-only list of every store the signed-in user can open (KAN-61), across all of their organisations.
 * It reads `GET /v1/organizations`, which returns only the caller's own memberships with their stores
 * (backend-organizations.md), so the browser never supplies an organisation id.
 */

/** The API's maximum page size; a user owns at most 10 organisations (MAX_OWNED_ORGANIZATIONS), so one page suffices. */
const ORGANIZATIONS_PAGE_SIZE = 100;

/** Page size and page cap when an organisation's embedded store list is truncated (bounds the extra calls). */
const STORES_PAGE_SIZE = 100;
const MAX_STORE_PAGES = 20;

export function flattenStores(
  organizations: ReadonlyArray<OrganizationData>
): ReadonlyArray<MerchantStore> {
  return organizations.flatMap((organization) =>
    organization.stores.map((store) => ({
      id: store.id,
      name: store.name,
      slug: store.slug,
      status: store.status,
      organizationId: organization.id,
      organizationName: organization.name,
    }))
  );
}

/**
 * `GET /v1/organizations` embeds at most 100 stores per organisation and sets `stores_truncated` beyond that.
 * The full list then comes from the per-organisation stores endpoint, page by page. Any failure fails the whole
 * call, so the switcher never silently shows a partial list.
 */
async function fetchAllStores(organizationId: string): Promise<ApiResult<StoreData[]>> {
  const stores: StoreData[] = [];
  for (let page = 0; page < MAX_STORE_PAGES; page += 1) {
    const result = await callBackend((client) =>
      listOrganizationStores({
        client,
        path: { organization_id: organizationId },
        query: { limit: STORES_PAGE_SIZE, offset: page * STORES_PAGE_SIZE },
      })
    );
    if (!result.success) return result;
    stores.push(...result.data);
    if (result.data.length < STORES_PAGE_SIZE) break;
  }
  return { success: true, data: stores };
}

async function withCompleteStores(
  organization: OrganizationData
): Promise<ApiResult<OrganizationData>> {
  if (!organization.stores_truncated) return { success: true, data: organization };
  const stores = await fetchAllStores(organization.id);
  if (!stores.success) return stores;
  return { success: true, data: { ...organization, stores: stores.data } };
}

export async function fetchMerchantStores(): Promise<ApiResult<ReadonlyArray<MerchantStore>>> {
  const result = await callBackend((client) =>
    listOrganizations({ client, query: { limit: ORGANIZATIONS_PAGE_SIZE } })
  );
  if (!result.success) return result;

  const complete = await Promise.all(result.data.map(withCompleteStores));
  const failed = complete.find((organization) => !organization.success);
  if (failed && !failed.success) return failed;
  return {
    success: true,
    data: flattenStores(
      complete.flatMap((organization) => (organization.success ? [organization.data] : []))
    ),
  };
}
