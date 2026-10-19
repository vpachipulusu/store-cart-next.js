'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import {
  readCart,
  removeLine,
  setQuantity,
  type Cart,
  type CartReply,
} from '@/lib/storefront/cart-client';
import { formatMoney } from '@/lib/storefront/catalogue';
import { productPath } from '@/lib/storefront/seo';
import { parseQuantity } from './add-to-cart';

type Line = Cart['lines'][number];

const STATUS_TEXT: Record<Line['status'], string | null> = {
  ok: null,
  unavailable: 'No longer available',
  out_of_stock: 'Out of stock',
  limited: 'Only some in stock: lower the quantity',
};

interface LineProps {
  line: Line;
  currency: string;
  isBusy: boolean;
  onChange: (
    change: () => Promise<CartReply>,
    done: string,
    isRemoval: boolean
  ) => Promise<boolean>;
}

/** One line: a small form (Enter or Update commits the quantity) and Remove. Controls stay focusable while busy. */
function BasketLine({ line, currency, isBusy, onChange }: LineProps) {
  const [draft, setDraft] = useState(String(line.quantity));
  const note = STATUS_TEXT[line.status];
  const inputId = `qty-${line.variant_id}`;

  return (
    <li className="flex flex-wrap items-start gap-4 py-5">
      <div className="min-w-0 flex-1">
        <Link
          href={productPath(line.product_slug)}
          className="font-medium underline-offset-4 hover:underline"
        >
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
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (isBusy) return;
          const quantity = parseQuantity(draft);
          setDraft(String(quantity));
          if (quantity !== line.quantity) {
            // A refused change (stock, rate limit) puts the field back to what the basket holds.
            void onChange(
              () => setQuantity(line.variant_id, quantity),
              `${line.product_name} quantity is now ${quantity}.`,
              false
            ).then((isSaved) => {
              if (!isSaved) setDraft(String(line.quantity));
            });
          }
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Quantity of {line.product_name}
        </label>
        <input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={1}
          max={99}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="h-11 w-20 rounded-md border border-input bg-background px-3 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <Button type="submit" variant="outline" aria-disabled={isBusy}>
          Update<span className="sr-only"> {line.product_name}</span>
        </Button>
        <Button
          type="button"
          variant="ghost"
          aria-disabled={isBusy}
          onClick={() => {
            if (!isBusy) {
              void onChange(
                () => removeLine(line.variant_id),
                `Removed ${line.product_name}.`,
                true
              );
            }
          }}
        >
          Remove<span className="sr-only"> {line.product_name}</span>
        </Button>
      </form>
      <p className="w-24 text-right font-medium tabular-nums">
        {formatMoney(line.line_total_minor, currency)}
      </p>
    </li>
  );
}

/**
 * The shopper's basket for this store, read from the cart route after the page loads. Prices and stock come from
 * the backend on every call. Checkout is a later story (KAN-77), so there is no checkout button yet.
 */
export function BasketView({ currency }: { currency: string }) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const summaryRef = useRef<HTMLHeadingElement>(null);
  const continueRef = useRef<HTMLAnchorElement>(null);

  const load = useCallback(async () => {
    const reply = await readCart();
    if (reply.ok) {
      setCart(reply.cart);
      setError(null);
    } else {
      setError(reply.error);
    }
  }, []);

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

  async function handleChange(
    change: () => Promise<CartReply>,
    done: string,
    isRemoval: boolean
  ): Promise<boolean> {
    setIsBusy(true);
    const reply = await change();
    setIsBusy(false);
    if (!reply.ok) {
      setError(reply.error);
      return false;
    }
    setError(null);
    setCart(reply.cart);
    setMessage(`${done} Total ${formatMoney(reply.cart.total_minor, currency)}.`);
    // A removed line takes its focused button with it: move focus somewhere that still exists.
    if (isRemoval) {
      requestAnimationFrame(() => {
        (reply.cart.lines.length === 0 ? continueRef.current : summaryRef.current)?.focus();
      });
    }
    return true;
  }

  const announcements = (
    <>
      <p role="status" aria-live="polite" className="sr-only">
        {message}
      </p>
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </>
  );

  if (cart === null) {
    return (
      <div className="py-12 text-center">
        {error ? (
          <Button type="button" variant="outline" onClick={() => void load()}>
            Try again
          </Button>
        ) : (
          <p role="status" className="text-muted-foreground">
            Loading your basket…
          </p>
        )}
        {announcements}
      </div>
    );
  }

  if (cart.lines.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Your basket is empty.</p>
        <Button asChild variant="accent" size="lg" className="mt-6">
          <Link ref={continueRef} href="/">
            Continue shopping
          </Link>
        </Button>
        {announcements}
      </div>
    );
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_20rem]">
      <ul className="divide-y border-y" aria-busy={isBusy}>
        {cart.lines.map((line) => (
          <BasketLine
            key={line.variant_id}
            line={line}
            currency={currency}
            isBusy={isBusy}
            onChange={handleChange}
          />
        ))}
      </ul>

      <section
        aria-labelledby="summary-heading"
        className="h-fit rounded-lg border bg-card p-6 text-card-foreground"
      >
        <h2
          id="summary-heading"
          ref={summaryRef}
          tabIndex={-1}
          className="font-display text-xl outline-none"
        >
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
      <div className="lg:col-span-2">{announcements}</div>
    </div>
  );
}
