import type { Metadata } from 'next';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { checkoutReturnMetadata } from '@/lib/storefront/seo';

/**
 * Where Stripe sends the shopper who backed out of checkout (KAN-77). Nothing was charged and the basket is
 * untouched. Rendered per request (Cache-Control no-store) and never indexed.
 */

export const dynamic = 'force-dynamic';

export const metadata: Metadata = checkoutReturnMetadata('Checkout cancelled');

export default function CheckoutCancelPage() {
  return (
    <div className="mx-auto max-w-xl py-12 text-center">
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        Checkout cancelled
      </h1>
      <p className="mt-4 text-muted-foreground">
        You have not been charged. Your basket is still here when you are ready.
      </p>
      <Button asChild variant="accent" size="lg" className="mt-8">
        <Link href="/basket">Back to your basket</Link>
      </Button>
    </div>
  );
}
