import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { StoreHeader } from '@/components/storefront/store-header';
import { getCategories, getPublicStore } from '@/lib/api/storefront-catalogue';
import { childCategories } from '@/lib/storefront/catalogue';
import { storeMetadata } from '@/lib/storefront/seo';
import { originFor } from '@/lib/storefront/store-origin';

/**
 * Storefront theme (KAN-75), reached only through the proxy rewrite from `{slug}.<platform root domain>`; the proxy
 * sends direct `/storefront/...` requests to the 404. The pages render from per-store cached reads (tag
 * `storefront:{slug}`), so they never read cookies or request headers: the basket count and the basket itself load
 * in the browser from the cart route handlers.
 */

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const store = await getPublicStore(slug);
  if (!store) return { title: 'Store not found', robots: { index: false, follow: false } };
  return storeMetadata(store, originFor(slug));
}

export default async function StorefrontLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Params;
}) {
  const { slug } = await params;
  const [store, categories] = await Promise.all([getPublicStore(slug), getCategories(slug)]);
  if (!store) notFound();

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        Skip to content
      </a>
      <StoreHeader storeName={store.name} categories={childCategories(categories ?? [], null)} />
      <main id="main" className="container flex-1 py-8 sm:py-12">
        {children}
      </main>
      <footer className="border-t">
        <div className="container flex flex-wrap items-center justify-between gap-2 py-6 text-sm text-muted-foreground">
          <p>
            © {new Date().getFullYear()} {store.name}
          </p>
          <p>Powered by StoreCart</p>
        </div>
      </footer>
    </div>
  );
}
