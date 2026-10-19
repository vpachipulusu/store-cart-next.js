import 'server-only';

import { revalidateTag } from 'next/cache';
import { storefrontTag } from './cache';

/**
 * Refresh one store's cached storefront pages (KAN-75) after a merchant or admin change.
 *
 * - `edit` (a new product, a price, an image): stale-while-revalidate (`'max'`). The next visitor still gets the
 *   cached page at once while it rebuilds; the cart re-prices every line anyway.
 * - `remove` (a delete, an unpublish, a store suspension): expire now, so nothing that must disappear is served
 *   again from the cache.
 */
export type StorefrontChange = 'edit' | 'remove';

export function refreshStorefront(storeSlug: string, change: StorefrontChange): void {
  revalidateTag(storefrontTag(storeSlug), change === 'remove' ? { expire: 0 } : 'max');
}
