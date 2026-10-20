import type { Metadata } from 'next';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { checkoutReturnMetadata } from '@/lib/storefront/seo';

/**
 * Where Stripe sends the shopper after paying (KAN-77). It marks nothing paid and reads no query or cookie: the
 * order is confirmed only by the Connect webhook, so this page only says the payment is being confirmed. Rendered
 * per request (so Cache-Control is no-store) and never indexed. The basket is left as it is: there is no
 * shopper-facing order read yet, so the page cannot tell when the order is paid (known limit).
 */

export const dynamic = 'force-dynamic';

export const metadata: Metadata = checkoutReturnMetadata('Order received');

export default function CheckoutSuccessPage() {
  return (
    <div className="mx-auto max-w-xl py-12 text-center">
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        Thank you for your order
      </h1>
      <p className="mt-4 text-muted-foreground">
        We are confirming your order with the payment provider, which can take a few moments.
      </p>
      <Button asChild variant="accent" size="lg" className="mt-8">
        <Link href="/">Continue shopping</Link>
      </Button>
    </div>
  );
}
