/** KAN-75: per-store SEO metadata, canonical URLs, Open Graph and Product structured data. */
import { describe, expect, it } from 'vitest';
import type { ProductDetail } from '@/lib/storefront/catalogue';
import {
  basketMetadata,
  categoryMetadata,
  categoryPath,
  homeMetadata,
  productJsonLd,
  productMetadata,
  searchMetadata,
  serializeJsonLd,
  storeMetadata,
  storeOrigin,
} from '@/lib/storefront/seo';

const STORE = { name: 'Acme Goods', slug: 'acme' };
const ORIGIN = 'https://acme.storecart.com';

const product = (over: Partial<ProductDetail> = {}): ProductDetail => ({
  title: 'Blue Mug',
  slug: 'blue-mug',
  description: 'A sturdy\nblue mug.',
  currency: 'GBP',
  options: [],
  variants: [
    {
      id: 'v1',
      priceMinor: 1250,
      compareAtPriceMinor: null,
      inStock: true,
      optionValueIds: [],
    },
  ],
  images: [{ url: 'https://img.example/a.jpg', alt: 'Blue mug' }],
  categories: [],
  ...over,
});

describe('storeOrigin', () => {
  it('is https on the store subdomain in production', () => {
    expect(storeOrigin('acme', 'storecart.com')).toBe(ORIGIN);
  });

  it('is http with the port on *.localhost', () => {
    expect(storeOrigin('acme', 'localhost', '4321')).toBe('http://acme.localhost:4321');
    expect(storeOrigin('acme', 'localhost')).toBe('http://acme.localhost:3000');
    expect(storeOrigin('acme', 'localhost', 'bad')).toBe('http://acme.localhost:3000');
  });
});

describe('store metadata', () => {
  it('names the store, sets the base URL and clears the platform keys', () => {
    const metadata = storeMetadata(STORE, ORIGIN);

    expect(metadata.metadataBase?.toString()).toBe(`${ORIGIN}/`);
    expect(metadata.title).toEqual({ default: 'Acme Goods', template: '%s | Acme Goods' });
    expect(metadata.openGraph).toMatchObject({ siteName: 'Acme Goods', url: `${ORIGIN}/` });
    expect(metadata.keywords).toBeNull();
    expect(metadata.authors).toBeNull();
    expect(metadata.creator).toBeNull();
    expect(metadata.robots).toEqual({ index: true, follow: true });
  });

  it('gives the home page the store root as canonical', () => {
    expect(homeMetadata(STORE, ORIGIN).alternates?.canonical).toBe(`${ORIGIN}/`);
  });
});

describe('category metadata', () => {
  const category = { name: 'Mugs', slug: 'mugs', parentSlug: null };

  it('page 1 is the bare category URL', () => {
    const metadata = categoryMetadata(STORE, category, ORIGIN);
    expect(metadata.title).toBe('Mugs');
    expect(metadata.alternates?.canonical).toBe(`${ORIGIN}/categories/mugs`);
    expect(metadata.openGraph).toMatchObject({ url: `${ORIGIN}/categories/mugs`, siteName: 'Acme Goods' });
  });

  it('later pages have their own canonical URL', () => {
    const metadata = categoryMetadata(STORE, category, ORIGIN, 3);
    expect(metadata.title).toBe('Mugs (page 3)');
    expect(metadata.alternates?.canonical).toBe(`${ORIGIN}/categories/mugs/page/3`);
    expect(categoryPath('mugs', 1)).toBe('/categories/mugs');
  });
});

describe('product metadata', () => {
  it('uses the description, the canonical product URL and the first image', () => {
    const metadata = productMetadata(STORE, product(), ORIGIN);

    expect(metadata.title).toBe('Blue Mug');
    expect(metadata.description).toBe('A sturdy blue mug.');
    expect(metadata.alternates?.canonical).toBe(`${ORIGIN}/products/blue-mug`);
    expect(metadata.openGraph).toMatchObject({
      url: `${ORIGIN}/products/blue-mug`,
      images: [{ url: 'https://img.example/a.jpg', alt: 'Blue mug' }],
    });
    expect(metadata.twitter).toMatchObject({ card: 'summary_large_image' });
  });

  it('falls back to a generated description and a small card without images', () => {
    const metadata = productMetadata(STORE, product({ description: null, images: [] }), ORIGIN);

    expect(metadata.description).toBe('Blue Mug from Acme Goods.');
    expect(metadata.twitter).toMatchObject({ card: 'summary' });
  });
});

describe('pages that are never indexed', () => {
  it('search is noindex but followed', () => {
    const metadata = searchMetadata(ORIGIN, 'mug');
    expect(metadata.robots).toEqual({ index: false, follow: true });
    expect(metadata.title).toBe('Search: mug');
    expect(searchMetadata(ORIGIN, '').title).toBe('Search');
  });

  it('the basket is noindex, nofollow', () => {
    expect(basketMetadata().robots).toEqual({ index: false, follow: false });
  });
});

describe('Product structured data', () => {
  it('has a single offer for one price', () => {
    const data = productJsonLd(STORE, product(), ORIGIN);
    expect(data).toMatchObject({
      '@type': 'Product',
      name: 'Blue Mug',
      brand: { name: 'Acme Goods' },
      offers: {
        '@type': 'Offer',
        price: '12.50',
        priceCurrency: 'GBP',
        availability: 'https://schema.org/InStock',
      },
    });
  });

  it('has an aggregate offer for a price range and reports out of stock', () => {
    const variants = [
      { id: 'a', priceMinor: 1000, compareAtPriceMinor: null, inStock: false, optionValueIds: [] },
      { id: 'b', priceMinor: 1500, compareAtPriceMinor: null, inStock: false, optionValueIds: [] },
    ];
    const data = productJsonLd(STORE, product({ variants, currency: 'JPY' }), ORIGIN);
    expect(data.offers).toMatchObject({
      '@type': 'AggregateOffer',
      lowPrice: '1000',
      highPrice: '1500',
      offerCount: 2,
      availability: 'https://schema.org/OutOfStock',
    });
  });

  it('has no offer without variants', () => {
    expect(productJsonLd(STORE, product({ variants: [] }), ORIGIN)).not.toHaveProperty('offers');
  });

  it('serialises without anything that could close the script element', () => {
    const json = serializeJsonLd({ name: '</script><script>alert(1)</script> & co' });
    expect(json).not.toMatch(/[<>&]/);
    expect(JSON.parse(json)).toEqual({ name: '</script><script>alert(1)</script> & co' });
  });
});
