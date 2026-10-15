import 'server-only';

import { cache } from 'react';
import { cookies } from 'next/headers';
import { fetchMerchantStores } from '@/lib/api/stores';
import { resolveStoreSelection, SELECTED_STORE_COOKIE, type StoreSelection } from './selection';

export type CurrentStoreSelection =
  | ({ available: true } & StoreSelection)
  | { available: false; error: string };

/**
 * The stores the signed-in user may open and the one the dashboard is scoped to (KAN-61). The cookie is
 * re-validated against the backend's list on every request; deduplicated per request so the layout and any
 * page that needs the store share one backend call.
 */
export const getCurrentStoreSelection = cache(async (): Promise<CurrentStoreSelection> => {
  const stores = await fetchMerchantStores();
  if (!stores.success) return { available: false, error: stores.error };
  const requested = (await cookies()).get(SELECTED_STORE_COOKIE)?.value;
  return { available: true, ...resolveStoreSelection(stores.data, requested) };
});
