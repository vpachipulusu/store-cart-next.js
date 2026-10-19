import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ImageOff } from 'lucide-react';
import { AddToCart } from '@/components/storefront/add-to-cart';
import { Breadcrumbs, type Crumb } from '@/components/storefront/breadcrumbs';
import { getCategories, getProduct, getPublicStore } from '@/lib/api/storefront-catalogue';
import { categoryTrail } from '@/lib/storefront/catalogue';
import {
  categoryPath,
  productJsonLd,
  productMetadata,
  serializeJsonLd,
} from '@/lib/storefront/seo';
import { originFor } from '@/lib/storefront/store-origin';

/** A published product (KAN-75): gallery, options, price, Add to basket, and Product structured data. */

export const revalidate = 300;

export function generateStaticParams(): { productSlug: string }[] {
  return [];
}

type Params = Promise<{ slug: string; productSlug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug, productSlug } = await params;
  const [store, product] = await Promise.all([getPublicStore(slug), getProduct(slug, productSlug)]);
  return store && product ? productMetadata(store, product, originFor(slug)) : {};
}

export default async function ProductPage({ params }: { params: Params }) {
  const { slug, productSlug } = await params;
  const [store, product, categories] = await Promise.all([
    getPublicStore(slug),
    getProduct(slug, productSlug),
    getCategories(slug),
  ]);
  if (!store || !product) notFound();

  const primary = product.categories[0];
  const trail = primary ? categoryTrail(categories ?? [], primary.slug) : [];
  const crumbs: Crumb[] = [
    { label: 'Home', href: '/' },
    ...trail.map((item) => ({ label: item.name, href: categoryPath(item.slug) })),
    { label: product.title },
  ];
  const [cover, ...more] = product.images;
  const jsonLd = serializeJsonLd(productJsonLd(store, product, originFor(slug)));

  return (
    <>
      <script
        type="application/ld+json"
        // serializeJsonLd escapes <, > and &, so merchant text cannot close the script element.
        dangerouslySetInnerHTML={{ __html: jsonLd }}
      />
      <Breadcrumbs items={crumbs} />
      <div className="grid gap-10 lg:grid-cols-2 lg:gap-16">
        <section aria-label="Product images" className="space-y-4">
          <div className="aspect-square overflow-hidden rounded-xl border bg-muted">
            {cover ? (
              // eslint-disable-next-line @next/next/no-img-element -- merchant images are served from the store's own image origin
              <img
                src={cover.url}
                alt={cover.alt}
                fetchPriority="high"
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                <ImageOff className="h-12 w-12" aria-hidden="true" />
                <span className="sr-only">No image</span>
              </div>
            )}
          </div>
          {more.length > 0 ? (
            <ul className="grid grid-cols-4 gap-3">
              {more.map((image) => (
                <li
                  key={image.url}
                  className="aspect-square overflow-hidden rounded-lg border bg-muted"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- see the cover image */}
                  <img
                    src={image.url}
                    alt={image.alt}
                    loading="lazy"
                    decoding="async"
                    className="h-full w-full object-cover"
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
            {product.title}
          </h1>
          <div className="mt-6">
            <AddToCart
              options={product.options}
              variants={product.variants}
              currency={product.currency}
            />
          </div>
          {product.description ? (
            <section aria-labelledby="description-heading" className="mt-10 border-t pt-8">
              <h2 id="description-heading" className="font-display text-xl font-semibold">
                Description
              </h2>
              <p className="mt-3 whitespace-pre-line leading-relaxed text-muted-foreground">
                {product.description}
              </p>
            </section>
          ) : null}
        </div>
      </div>
    </>
  );
}
