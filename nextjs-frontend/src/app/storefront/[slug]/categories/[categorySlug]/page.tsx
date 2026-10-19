import type { Metadata } from 'next';
import { CategoryListing, categoryListingMetadata } from '@/components/storefront/category-listing';

/** A category, page 1 (KAN-75). Cached per store. */

export const revalidate = 300;

export function generateStaticParams(): { categorySlug: string }[] {
  return [];
}

type Params = Promise<{ slug: string; categorySlug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug, categorySlug } = await params;
  return categoryListingMetadata(slug, categorySlug, 1);
}

export default async function CategoryPage({ params }: { params: Params }) {
  const { slug, categorySlug } = await params;
  return <CategoryListing slug={slug} categorySlug={categorySlug} page={1} />;
}
