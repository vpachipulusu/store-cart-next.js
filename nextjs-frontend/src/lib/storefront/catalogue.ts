/**
 * Storefront catalogue shapes and pure helpers (KAN-75). Safe for client code: no server imports.
 *
 * The backend public catalogue (`/v1/storefront/{slug}/products|categories`) is mapped into these camelCase
 * types by `src/lib/api/storefront-catalogue.ts`, keeping only the fields a shop window shows.
 */

export interface StoreImage {
  readonly url: string;
  readonly alt: string;
}

export interface ProductCard {
  readonly title: string;
  readonly slug: string;
  readonly minPriceMinor: number | null;
  readonly maxPriceMinor: number | null;
  readonly image: StoreImage | null;
}

export interface ProductPage {
  readonly items: readonly ProductCard[];
  readonly currency: string;
  readonly total: number;
  readonly page: number;
  readonly pageCount: number;
}

export interface StoreCategory {
  readonly name: string;
  readonly slug: string;
  readonly parentSlug: string | null;
}

export interface ProductOption {
  readonly name: string;
  readonly values: readonly { readonly id: string; readonly value: string }[];
}

export interface ProductVariant {
  readonly id: string;
  readonly priceMinor: number;
  readonly compareAtPriceMinor: number | null;
  readonly inStock: boolean;
  readonly optionValueIds: readonly string[];
}

export interface ProductDetail {
  readonly title: string;
  readonly slug: string;
  readonly description: string | null;
  readonly currency: string;
  readonly options: readonly ProductOption[];
  readonly variants: readonly ProductVariant[];
  readonly images: readonly StoreImage[];
  readonly categories: readonly StoreCategory[];
}

/** Products per listing page (the backend allows up to 100). */
export const PAGE_SIZE = 24;
/** Deepest page a listing serves; the backend caps the public offset at 10 000. */
export const MAX_PAGE = 400;
export const MAX_SEARCH_LENGTH = 100;

/** A 1-based page number from a URL value; anything else is page 1, and pages past MAX_PAGE are clamped. */
export function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === undefined || !/^[1-9]\d{0,5}$/.test(raw)) return 1;
  return Math.min(Number(raw), MAX_PAGE);
}

/** Trimmed search text with inner whitespace collapsed, cut to the backend limit; empty means no search. */
export function cleanSearch(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  return (raw ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_SEARCH_LENGTH).trim();
}

export function pageCount(total: number, size: number = PAGE_SIZE): number {
  return Math.min(Math.max(1, Math.ceil(total / size)), MAX_PAGE);
}

/** Minor units in the store currency, formatted for display ("£12.50"). An invalid code shows the code. */
export function formatMoney(minor: number, currency: string, locale = 'en-GB'): string {
  let formatter: Intl.NumberFormat;
  try {
    formatter = new Intl.NumberFormat(locale, { style: 'currency', currency });
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency}`;
  }
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  return formatter.format(minor / 10 ** digits);
}

/** "£12.00", "From £12.00" for a range, or null when the product has no price. */
export function formatPriceRange(
  min: number | null,
  max: number | null,
  currency: string
): string | null {
  if (min === null) return null;
  const from = formatMoney(min, currency);
  return max !== null && max > min ? `From ${from}` : from;
}

/** Children of `parentSlug` (roots for null), in the order the backend returned them. */
export function childCategories(
  categories: readonly StoreCategory[],
  parentSlug: string | null
): StoreCategory[] {
  return categories.filter((category) => category.parentSlug === parentSlug);
}

/** The category and its ancestors, root first. Stops on a cycle or a missing parent. */
export function categoryTrail(categories: readonly StoreCategory[], slug: string): StoreCategory[] {
  const bySlug = new Map(categories.map((category) => [category.slug, category]));
  const trail: StoreCategory[] = [];
  const seen = new Set<string>();
  let current = bySlug.get(slug);
  while (current && !seen.has(current.slug)) {
    trail.unshift(current);
    seen.add(current.slug);
    current = current.parentSlug ? bySlug.get(current.parentSlug) : undefined;
  }
  return trail;
}

function selectionKey(ids: readonly string[]): string {
  return [...ids].sort().join('|');
}

/** The variant whose option values are exactly `selected` (one value id per option), or null. */
export function findVariant(
  variants: readonly ProductVariant[],
  selected: readonly string[]
): ProductVariant | null {
  const wanted = selectionKey(selected);
  return variants.find((variant) => selectionKey(variant.optionValueIds) === wanted) ?? null;
}

/** The starting selection: the first in-stock variant's values, else the first variant's. */
export function initialSelection(variants: readonly ProductVariant[]): string[] {
  const start = variants.find((variant) => variant.inStock) ?? variants[0];
  return start ? [...start.optionValueIds] : [];
}

/** Plain text for a meta description: whitespace collapsed, cut at a word near `max` characters. */
export function summarise(text: string | null | undefined, max = 160): string | undefined {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim();
  if (!flat) return undefined;
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max - 1);
  const space = cut.lastIndexOf(' ');
  return `${(space > max / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
