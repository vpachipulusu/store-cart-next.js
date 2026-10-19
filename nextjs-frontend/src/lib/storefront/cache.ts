/**
 * Per-store cache tags for the storefront pages (KAN-75). Pure, so tests and server code share it.
 *
 * Every cached storefront read (store lookup, product lists, product pages, categories) carries the store's tag,
 * so one `revalidateTag(storefrontTag(slug))` refreshes that store's pages and no other store's. Merchant
 * catalogue writes call it (`src/app/actions/product-actions.ts`); anything else expires after
 * `STOREFRONT_REVALIDATE_SECONDS`, which also bounds how long a suspended store's pages stay cached.
 */

export const STOREFRONT_TAG_PREFIX = 'storefront:';
export const STOREFRONT_REVALIDATE_SECONDS = 300;

export function storefrontTag(slug: string): string {
  return `${STOREFRONT_TAG_PREFIX}${slug}`;
}

/** The `unstable_cache` key of one storefront read: the read's name, the store, then its arguments. */
export function storefrontCacheKey(
  read: string,
  slug: string,
  ...args: readonly (string | number | null | undefined)[]
): string[] {
  return [
    'storefront',
    read,
    slug,
    ...args.map((arg) => (arg === null || arg === undefined ? '' : String(arg))),
  ];
}
