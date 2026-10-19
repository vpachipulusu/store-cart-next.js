import 'server-only';

import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Breadcrumbs } from './breadcrumbs';
import { PageLinks } from './page-links';
import { ProductGrid } from './product-grid';
import { getCategories, getProductPage, getPublicStore } from '@/lib/api/storefront-catalogue';
import { categoryTrail, childCategories, type StoreCategory } from '@/lib/storefront/catalogue';
import { categoryMetadata, categoryPath } from '@/lib/storefront/seo';
import { originFor } from '@/lib/storefront/store-origin';

/**
 * A category listing (KAN-75), shared by `/categories/{slug}` (page 1) and `/categories/{slug}/page/{n}`. Paging
 * is in the path, not the query, so every page is cached per store and has its own canonical URL.
 */

async function findCategory(slug: string, categorySlug: string): Promise<{
  category: StoreCategory;
  categories: StoreCategory[];
} | null> {
  const categories = await getCategories(slug);
  const category = categories?.find((item) => item.slug === categorySlug);
  return categories && category ? { category, categories } : null;
}

export async function categoryListingMetadata(
  slug: string,
  categorySlug: string,
  page: number
): Promise<Metadata> {
  const [store, found] = await Promise.all([getPublicStore(slug), findCategory(slug, categorySlug)]);
  if (!store || !found) return {};
  return categoryMetadata(store, found.category, originFor(slug), page);
}

export async function CategoryListing({
  slug,
  categorySlug,
  page,
}: {
  slug: string;
  categorySlug: string;
  page: number;
}) {
  const found = await findCategory(slug, categorySlug);
  if (!found) notFound();
  const products = await getProductPage(slug, categorySlug, page);
  if (!products || (page > 1 && page > products.pageCount)) notFound();

  const { category, categories } = found;
  const trail = categoryTrail(categories, category.slug);
  const children = childCategories(categories, category.slug);

  return (
    <>
      <Breadcrumbs
        items={[
          { label: 'Home', href: '/' },
          ...trail.map((item) => ({ label: item.name, href: categoryPath(item.slug) })),
        ]}
      />
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-5xl">{category.name}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {products.total} {products.total === 1 ? 'product' : 'products'}
      </p>
      {children.length > 0 ? (
        <nav aria-label={`${category.name} subcategories`} className="mt-6">
          <ul className="flex flex-wrap gap-2">
            {children.map((child) => (
              <li key={child.slug}>
                <Link
                  href={categoryPath(child.slug)}
                  className="inline-flex h-11 items-center rounded-full border px-4 text-sm hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {child.name}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
      <div className="mt-8">
        <ProductGrid
          products={products.items}
          currency={products.currency}
          emptyMessage="No products in this category yet."
        />
      </div>
      <PageLinks
        page={products.page}
        pageCount={products.pageCount}
        hrefFor={(target) => categoryPath(category.slug, target)}
      />
    </>
  );
}
