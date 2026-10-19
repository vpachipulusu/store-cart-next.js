import Link from 'next/link';

/** A missing product, category or page inside a live store (KAN-75). The store's header and footer stay. */
export default function StoreNotFound() {
  return (
    <section className="mx-auto max-w-md py-16 text-center">
      <p className="font-display text-6xl text-accent-ink" aria-hidden="true">
        404
      </p>
      <h1 className="mt-2 font-display text-2xl font-semibold">We could not find that page</h1>
      <p className="mt-2 text-muted-foreground">It may have moved or is no longer available.</p>
      <Link
        href="/"
        className="mt-6 inline-flex h-12 items-center rounded-md bg-cta px-8 text-sm font-medium text-cta-foreground hover:bg-cta-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        Back to the shop
      </Link>
    </section>
  );
}
