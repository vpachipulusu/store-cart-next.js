import Link from 'next/link';
import { ImageOff } from 'lucide-react';
import { formatPriceRange, type ProductCard } from '@/lib/storefront/catalogue';
import { productPath } from '@/lib/storefront/seo';

interface ProductGridProps {
  products: readonly ProductCard[];
  currency: string;
  /** Heading level of each card title, so the page outline stays in order. */
  headingLevel?: 'h2' | 'h3';
  emptyMessage?: string;
}

/** Responsive product cards: image, title and price, each card one link. */
export function ProductGrid({
  products,
  currency,
  headingLevel: Heading = 'h2',
  emptyMessage = 'No products here yet.',
}: ProductGridProps) {
  if (products.length === 0) {
    return <p className="py-12 text-center text-muted-foreground">{emptyMessage}</p>;
  }
  return (
    <ul className="grid grid-cols-2 gap-4 sm:gap-6 md:grid-cols-3 lg:grid-cols-4">
      {products.map((product) => {
        const price = formatPriceRange(product.minPriceMinor, product.maxPriceMinor, currency);
        return (
          <li key={product.slug}>
            <Link
              href={productPath(product.slug)}
              className="group block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <div className="aspect-square overflow-hidden rounded-lg border bg-muted">
                {product.image ? (
                  // eslint-disable-next-line @next/next/no-img-element -- merchant images are served from the store's own image origin
                  <img
                    src={product.image.url}
                    alt={product.image.alt}
                    loading="lazy"
                    decoding="async"
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-muted-foreground">
                    <ImageOff className="h-8 w-8" aria-hidden="true" />
                  </div>
                )}
              </div>
              <Heading className="mt-3 line-clamp-2 text-sm font-medium group-hover:underline sm:text-base">
                {product.title}
              </Heading>
              {price ? (
                <p className="mt-1 text-sm tabular-nums text-muted-foreground">{price}</p>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
