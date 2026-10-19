import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowRight } from 'lucide-react';
import { ProductGrid } from '@/components/storefront/product-grid';
import { getCategories, getProductPage, getPublicStore } from '@/lib/api/storefront-catalogue';
import { childCategories } from '@/lib/storefront/catalogue';
import { categoryPath, homeMetadata } from '@/lib/storefront/seo';
import { originFor } from '@/lib/storefront/store-origin';

/** Store home (KAN-75): welcome, top-level categories and the newest products. Cached per store. */

export const revalidate = 300;

export function generateStaticParams(): { slug: string }[] {
  return [];
}

type Params = Promise<{ slug: string }>;

const NEW_ARRIVALS = 8;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const store = await getPublicStore(slug);
  return store ? homeMetadata(store, originFor(slug)) : {};
}

export default async function StoreHomePage({ params }: { params: Params }) {
  const { slug } = await params;
  const [store, products, categories] = await Promise.all([
    getPublicStore(slug),
    getProductPage(slug, null, 1),
    getCategories(slug),
  ]);
  if (!store || !products) notFound();
  const roots = childCategories(categories ?? [], null);

  return (
    <div className="space-y-16">
      <section
        aria-labelledby="welcome"
        className="rounded-xl border bg-secondary px-6 py-12 sm:px-12 sm:py-16"
      >
        <p className="text-sm font-medium uppercase tracking-widest text-accent-ink">Welcome to</p>
        <h1
          id="welcome"
          className="mt-3 font-display text-4xl font-semibold tracking-tight sm:text-6xl"
        >
          {store.name}
        </h1>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Browse our newest products and find something you love.
        </p>
        <Link
          href="/search"
          className="mt-8 inline-flex h-12 items-center gap-2 rounded-md bg-cta px-8 text-sm font-medium text-cta-foreground hover:bg-cta-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          Shop all products
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </section>

      {roots.length > 0 ? (
        <section aria-labelledby="categories-heading">
          <h2 id="categories-heading" className="font-display text-2xl font-semibold sm:text-3xl">
            Shop by category
          </h2>
          <ul className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {roots.map((category) => (
              <li key={category.slug}>
                <Link
                  href={categoryPath(category.slug)}
                  className="flex h-full min-h-20 items-center justify-between gap-2 rounded-lg border bg-card p-4 font-medium text-card-foreground transition-colors hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {category.name}
                  <ArrowRight
                    className="h-4 w-4 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="new-heading">
        <div className="flex items-end justify-between gap-4">
          <h2 id="new-heading" className="font-display text-2xl font-semibold sm:text-3xl">
            New arrivals
          </h2>
          {products.total > NEW_ARRIVALS ? (
            <Link href="/search" className="text-sm font-medium underline underline-offset-4">
              View all
            </Link>
          ) : null}
        </div>
        <div className="mt-6">
          <ProductGrid
            products={products.items.slice(0, NEW_ARRIVALS)}
            currency={products.currency}
            headingLevel="h3"
            emptyMessage="New products are coming soon."
          />
        </div>
      </section>
    </div>
  );
}
