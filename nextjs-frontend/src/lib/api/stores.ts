import 'server-only';

import { callBackend, type ApiResult } from './server';
import { listOrganizations, type OrganizationData } from './generated';
import type { MerchantStore } from '@/lib/stores/selection';

/**
 * Server-only list of every store the signed-in user can open (KAN-61), across all of their organisations.
 * It reads `GET /v1/organizations`, which returns only the caller's own memberships with their stores
 * (backend-organizations.md), so the browser never supplies an organisation id.
 */

/** The API's maximum page size; a user owns at most 10 organisations (MAX_OWNED_ORGANIZATIONS), so one page suffices. */
const ORGANIZATIONS_PAGE_SIZE = 100;

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

export async function fetchMerchantStores(): Promise<ApiResult<ReadonlyArray<MerchantStore>>> {
  const result = await callBackend((client) =>
    listOrganizations({ client, query: { limit: ORGANIZATIONS_PAGE_SIZE } })
  );
  if (!result.success) return result;
  return { success: true, data: flattenStores(result.data) };
}
