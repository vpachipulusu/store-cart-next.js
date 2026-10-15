/**
 * Store selection for the merchant dashboard (KAN-61). Pure and safe to import from client code.
 *
 * The selected store id lives in the `selected-store` cookie so server components can read it. The cookie is
 * only a preference: every request re-validates it against the stores the backend lists for the signed-in
 * user, and anything unknown falls back to the first store.
 */

export const SELECTED_STORE_COOKIE = 'selected-store';

export const STORE_NOT_AVAILABLE_MESSAGE = 'That store is not available to you';
export const STORES_UNAVAILABLE_MESSAGE = 'Could not load your stores. Please try again.';

/** Server-and-client shape of a store the signed-in user may open. */
export type MerchantStore = {
  id: string;
  name: string;
  slug: string;
  status: string;
  organizationId: string;
  organizationName: string;
};

export type StoreSelection = {
  stores: ReadonlyArray<MerchantStore>;
  /** `null` only when the user has no stores. */
  selected: MerchantStore | null;
};

/**
 * Store ids are cuid2 strings (24 lowercase alphanumerics, backend `new_id`). The pattern is deliberately looser
 * (it also admits legacy cuids and UUIDs) because it only screens out junk before a lookup; membership in the
 * user's own store list is the real check.
 */
const STORE_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function isStoreId(value: unknown): value is string {
  return typeof value === 'string' && STORE_ID_PATTERN.test(value);
}

/** Picks the requested store when the user may access it, else the first one, else none. */
export function resolveStoreSelection(
  stores: ReadonlyArray<MerchantStore>,
  requestedId: string | null | undefined
): StoreSelection {
  const requested = isStoreId(requestedId)
    ? stores.find((store) => store.id === requestedId)
    : undefined;
  return { stores, selected: requested ?? stores[0] ?? null };
}
