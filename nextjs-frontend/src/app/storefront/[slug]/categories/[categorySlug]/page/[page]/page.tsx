import type { Metadata } from 'next';
import { notFound, permanentRedirect } from 'next/navigation';
import { CategoryListing, categoryListingMetadata } from '@/components/storefront/category-listing';
import { MAX_PAGE } from '@/lib/storefront/catalogue';
import { categoryPath } from '@/lib/storefront/seo';

/** A category, page 2 and later (KAN-75). Page 1 lives at the bare category URL. Cached per store. */

export const revalidate = 300;

export function generateStaticParams(): { page: string }[] {
  return [];
}

type Params = Promise<{ slug: string; categorySlug: string; page: string }>;

/** 1..MAX_PAGE written canonically ("2", not "02"), else null. */
function pageNumber(raw: string): number | null {
  if (!/^[1-9]\d{0,5}$/.test(raw)) return null;
  const page = Number(raw);
  return page <= MAX_PAGE ? page : null;
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug, categorySlug, page } = await params;
  const number = pageNumber(page);
  return number && number > 1 ? categoryListingMetadata(slug, categorySlug, number) : {};
}

export default async function CategoryPagedPage({ params }: { params: Params }) {
  const { slug, categorySlug, page } = await params;
  const number = pageNumber(page);
  if (number === null) notFound();
  if (number === 1) permanentRedirect(categoryPath(categorySlug));
  return <CategoryListing slug={slug} categorySlug={categorySlug} page={number} />;
}
