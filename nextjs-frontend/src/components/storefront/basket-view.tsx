'use client';

import { useEffect, useState, useTransition } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { readCart, removeLine, setQuantity, type Cart, type CartReply } from '@/lib/storefront/cart-client';
import { formatMoney } from '@/lib/storefront/catalogue';
import { productPath } from '@/lib/storefront/seo';

type LineStatus = Cart['lines'][number]['status'];

const STATUS_TEXT: Record<LineStatus, string | null> = {
  ok: null,
  unavailable: 'No longer available',
  out_of_stock: 'Out of stock',
  limited: 'Only some in stock: lower the quantity',
};

const MAX_QUANTITY = 99;

/**
 * The shopper's basket for this store, read from the cart route after the page loads. Prices and stock come from
 * the backend on every call. Checkout is a later story (KAN-77), so there is no checkout button yet.
 */
export function BasketView({ currency }: { currency: string }) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let isActive = true;
    void readCart().then((reply) => {
      if (!isActive) return;
      if (reply.ok) setCart(reply.cart);
      else setError(reply.error);
    });
    return () => {
      isActive = false;
    };
  }, []);

  function apply(change: () => Promise<CartReply>) {
    startTransition(async () => {
      const reply = await change();
      if (reply.ok) {
        setCart(reply.cart);
        setError(null);
      } else {
        setError(reply.error);
      }
    });
  }

  if (cart === null) {
    return (
      <p role="status" aria-live="polite" className="py-12 text-center text-muted-foreground">
        {error ?? 'Loading your basket…'}
      </p>
    );
  }

  if (cart.lines.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Your basket is empty.</p>
        <Button asChild variant="accent" size="lg" className="mt-6">
          <Link href="/">Continue shopping</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_20rem]">
      <ul className="divide-y border-y" aria-busy={isPending}>
        {cart.lines.map((line) => {
          const note = STATUS_TEXT[line.status];
          const inputId = `qty-${line.variant_id}`;
          return (
            <li key={line.variant_id} className="flex flex-wrap items-start gap-4 py-5">
              <div className="min-w-0 flex-1">
                <Link href={productPath(line.product_slug)} className="font-medium underline-offset-4 hover:underline">
                  {line.product_name}
                </Link>
                {line.variant_label ? (
                  <p className="text-sm text-muted-foreground">{line.variant_label}</p>
                ) : null}
                <p className="mt-1 text-sm tabular-nums text-muted-foreground">
                  {formatMoney(line.unit_price_minor, currency)} each
                </p>
                {note ? <p className="mt-1 text-sm font-medium text-destructive">{note}</p> : null}
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor={inputId} className="sr-only">
                  Quantity of {line.product_name}
                </label>
                <input
                  id={inputId}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={MAX_QUANTITY}
                  key={`${line.variant_id}-${line.quantity}`}
                  defaultValue={line.quantity}
                  disabled={isPending}
                  onBlur={(event) => {
                    const next = Number(event.target.value);
                    if (!Number.isInteger(next) || next < 1 || next > MAX_QUANTITY) {
                      event.target.value = String(line.quantity);
                      return;
                    }
                    if (next !== line.quantity) apply(() => setQuantity(line.variant_id, next));
                  }}
                  className="h-11 w-20 rounded-md border border-input bg-background px-3 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => apply(() => removeLine(line.variant_id))}
                  disabled={isPending}
                >
                  Remove<span className="sr-only"> {line.product_name}</span>
                </Button>
              </div>
              <p className="w-24 text-right font-medium tabular-nums">
                {formatMoney(line.line_total_minor, currency)}
              </p>
            </li>
          );
        })}
      </ul>

      <section aria-labelledby="summary-heading" className="h-fit rounded-lg border bg-card p-6 text-card-foreground">
        <h2 id="summary-heading" className="font-display text-xl">
          Summary
        </h2>
        <dl className="mt-4 space-y-2 text-sm tabular-nums">
          <div className="flex justify-between">
            <dt>Subtotal</dt>
            <dd>{formatMoney(cart.subtotal_minor, currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Shipping</dt>
            <dd>{formatMoney(cart.shipping_minor, currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>{cart.prices_include_tax ? 'Tax (included)' : 'Tax'}</dt>
            <dd>{formatMoney(cart.tax_minor, currency)}</dd>
          </div>
          <div className="flex justify-between border-t pt-2 text-base font-semibold">
            <dt>Total</dt>
            <dd>{formatMoney(cart.total_minor, currency)}</dd>
          </div>
        </dl>
        <p className="mt-4 text-sm text-muted-foreground">Checkout is coming soon.</p>
      </section>

      <p role="status" aria-live="polite" className="text-sm text-destructive lg:col-span-2">
        {error}
      </p>
    </div>
  );
}
