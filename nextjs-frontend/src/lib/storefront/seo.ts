import type { Metadata } from 'next';
import { DEFAULT_PLATFORM_ROOT_DOMAIN } from './host';
import { summarise, type ProductDetail, type StoreCategory } from './catalogue';

/**
 * Per-store SEO (KAN-75): canonical URLs on the store's own host, Open Graph and Product structured data.
 * Pure: the origin is passed in, so the same code serves `{slug}.storecart.com` and `{slug}.localhost:3000`.
 */

export interface SeoStore {
  readonly name: string;
  readonly slug: string;
}

/**
 * `https://{slug}.{root}` in production; `http://{slug}.localhost:{port}` when the root domain is the
 * development default (browsers resolve `*.localhost` to loopback, without TLS).
 */
export function storeOrigin(slug: string, rootDomain: string, port?: string): string {
  if (rootDomain === DEFAULT_PLATFORM_ROOT_DOMAIN) {
    return `http://${slug}.${rootDomain}:${port && /^\d{1,5}$/.test(port) ? port : '3000'}`;
  }
  return `https://${slug}.${rootDomain}`;
}

/** Keys the root layout sets for the platform that must not describe a merchant's store. */
const NOT_THE_PLATFORM = {
  keywords: null,
  authors: null,
  creator: null,
  manifest: null,
} as const;

/** Store-wide defaults from the storefront layout: title template, base URL, Open Graph site name. */
export function storeMetadata(store: SeoStore, origin: string): Metadata {
  const description = `Shop ${store.name} online.`;
  return {
    ...NOT_THE_PLATFORM,
    metadataBase: new URL(origin),
    title: { default: store.name, template: `%s | ${store.name}` },
    description,
    applicationName: store.name,
    openGraph: {
      type: 'website',
      siteName: store.name,
      title: store.name,
      description,
      url: `${origin}/`,
    },
    twitter: { card: 'summary', title: store.name, description },
    robots: { index: true, follow: true },
  };
}

export function homeMetadata(store: SeoStore, origin: string): Metadata {
  return {
    title: { absolute: store.name },
    alternates: { canonical: `${origin}/` },
  };
}

/** Page 1 is the bare category URL; later pages are their own canonical URLs. */
export function categoryPath(slug: string, page = 1): string {
  return page > 1 ? `/categories/${slug}/page/${page}` : `/categories/${slug}`;
}

export function categoryMetadata(
  store: SeoStore,
  category: StoreCategory,
  origin: string,
  page = 1
): Metadata {
  const title = page > 1 ? `${category.name} (page ${page})` : category.name;
  const description = `${category.name} at ${store.name}.`;
  const url = `${origin}${categoryPath(category.slug, page)}`;
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { type: 'website', siteName: store.name, title, description, url },
    twitter: { card: 'summary', title, description },
  };
}

export function productPath(slug: string): string {
  return `/products/${slug}`;
}

export function productMetadata(store: SeoStore, product: ProductDetail, origin: string): Metadata {
  const description = summarise(product.description) ?? `${product.title} from ${store.name}.`;
  const url = `${origin}${productPath(product.slug)}`;
  const image = product.images[0];
  const images = image ? [{ url: image.url, alt: image.alt }] : undefined;
  return {
    title: product.title,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: 'website',
      siteName: store.name,
      title: product.title,
      description,
      url,
      images,
    },
    twitter: {
      card: image ? 'summary_large_image' : 'summary',
      title: product.title,
      description,
      images: image ? [image.url] : undefined,
    },
  };
}

/** Search results are never indexed (endless query URLs); links on them are still followed. */
export function searchMetadata(origin: string, query: string): Metadata {
  return {
    title: query ? `Search: ${query}` : 'Search',
    alternates: { canonical: `${origin}/search` },
    robots: { index: false, follow: true },
  };
}

export function basketMetadata(): Metadata {
  return { title: 'Basket', robots: { index: false, follow: false } };
}

/** Major-unit decimal string for structured data ("12.50"); exponent from the currency. */
function decimalPrice(minor: number, currency: string): string {
  let digits = 2;
  try {
    digits =
      new Intl.NumberFormat('en', { style: 'currency', currency }).resolvedOptions()
        .maximumFractionDigits ?? 2;
  } catch {
    digits = 2;
  }
  return (minor / 10 ** digits).toFixed(digits);
}

/** schema.org Product with an offer (or an aggregate offer for a price range). */
export function productJsonLd(
  store: SeoStore,
  product: ProductDetail,
  origin: string
): Record<string, unknown> {
  const prices = product.variants.map((variant) => variant.priceMinor);
  const inStock = product.variants.some((variant) => variant.inStock);
  const availability = `https://schema.org/${inStock ? 'InStock' : 'OutOfStock'}`;
  const url = `${origin}${productPath(product.slug)}`;
  const low = prices.length ? Math.min(...prices) : null;
  const high = prices.length ? Math.max(...prices) : null;
  const offers =
    low === null || high === null
      ? undefined
      : low === high
        ? {
            '@type': 'Offer',
            price: decimalPrice(low, product.currency),
            priceCurrency: product.currency,
            availability,
            url,
          }
        : {
            '@type': 'AggregateOffer',
            lowPrice: decimalPrice(low, product.currency),
            highPrice: decimalPrice(high, product.currency),
            priceCurrency: product.currency,
            offerCount: prices.length,
            availability,
          };
  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: product.title,
    description: summarise(product.description, 5000),
    image: product.images.map((image) => image.url),
    url,
    brand: { '@type': 'Brand', name: store.name },
    ...(offers ? { offers } : {}),
  };
}

/**
 * JSON for an inline `<script type="application/ld+json">`. `<`, `>` and `&` are escaped so merchant text can
 * never close the script element.
 */
export function serializeJsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}
