import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { BasketView } from '@/components/storefront/basket-view';
import { getProductPage } from '@/lib/api/storefront-catalogue';
import { basketMetadata } from '@/lib/storefront/seo';

/**
 * The shopper's basket (KAN-75). `/cart` is the cart API (KAN-76), so the page lives at `/basket`. The shell is
 * cached; the lines load in the browser from the cart route. Checkout is KAN-77.
 */

export const revalidate = 300;

export function generateStaticParams(): { slug: string }[] {
  return [];
}

export const metadata: Metadata = basketMetadata();

export default async function BasketPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // The currency comes with any product listing; the cached first page costs nothing extra.
  const listing = await getProductPage(slug, null, 1);
  if (!listing) notFound();

  return (
    <>
      <h1 className="mb-8 font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        Your basket
      </h1>
      <BasketView currency={listing.currency} />
    </>
  );
}
