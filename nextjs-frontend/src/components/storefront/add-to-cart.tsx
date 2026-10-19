'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { addToCart } from '@/lib/storefront/cart-client';
import {
  findVariant,
  formatMoney,
  initialSelection,
  type ProductOption,
  type ProductVariant,
} from '@/lib/storefront/catalogue';

interface AddToCartProps {
  options: readonly ProductOption[];
  variants: readonly ProductVariant[];
  currency: string;
}

type Status =
  | { kind: 'idle' }
  | { kind: 'adding' }
  | { kind: 'added' }
  | { kind: 'error'; message: string };

const MAX_QUANTITY = 99;

/** A whole number from 1 to 99 from what the shopper typed; anything else is 1. */
export function parseQuantity(text: string): number {
  const value = Number(text);
  return Number.isInteger(value) ? Math.min(Math.max(value, 1), MAX_QUANTITY) : 1;
}

/** Option pickers, live price and stock, quantity, and Add to basket through this store's cart route. */
export function AddToCart({ options, variants, currency }: AddToCartProps) {
  const [selected, setSelected] = useState<string[]>(() => initialSelection(variants));
  const [quantityText, setQuantityText] = useState('1');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });

  const variant = findVariant(variants, selected);
  const canBuy = variant !== null && variant.inStock;
  const isAdding = status.kind === 'adding';
  const isBlocked = !canBuy || isAdding;

  function choose(option: ProductOption, valueId: string) {
    const others = selected.filter((id) => !option.values.some((value) => value.id === id));
    setSelected([...others, valueId]);
    setStatus({ kind: 'idle' });
  }

  async function handleAdd() {
    // aria-disabled keeps the button focusable, so the guard lives here.
    if (!variant || isBlocked) return;
    const quantity = parseQuantity(quantityText);
    setQuantityText(String(quantity));
    setStatus({ kind: 'adding' });
    const reply = await addToCart(variant.id, quantity);
    setStatus(reply.ok ? { kind: 'added' } : { kind: 'error', message: reply.error });
  }

  const availability =
    variant === null
      ? 'This combination is not available.'
      : variant.inStock
        ? 'In stock'
        : 'Out of stock';

  return (
    <div className="space-y-6">
      <div aria-live="polite">
        <p className="text-2xl font-semibold tabular-nums">
          {variant ? formatMoney(variant.priceMinor, currency) : 'Unavailable'}
          {variant?.compareAtPriceMinor ? (
            <s className="ml-3 text-base font-normal text-muted-foreground">
              <span className="sr-only">Was </span>
              {formatMoney(variant.compareAtPriceMinor, currency)}
            </s>
          ) : null}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{availability}</p>
      </div>

      {options.map((option, optionIndex) => (
        <fieldset key={option.name}>
          <legend className="mb-2 text-sm font-medium">{option.name}</legend>
          <div className="flex flex-wrap gap-2">
            {option.values.map((value) => (
              <label
                key={value.id}
                className="inline-flex h-11 min-w-11 cursor-pointer items-center justify-center rounded-md border border-input px-4 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary has-[:checked]:text-primary-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
              >
                <input
                  type="radio"
                  name={`option-${optionIndex}`}
                  value={value.id}
                  checked={selected.includes(value.id)}
                  onChange={() => choose(option, value.id)}
                  className="sr-only"
                />
                {value.value}
              </label>
            ))}
          </div>
        </fieldset>
      ))}

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="quantity" className="mb-2 block text-sm font-medium">
            Quantity
          </label>
          <input
            id="quantity"
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_QUANTITY}
            value={quantityText}
            onChange={(event) => setQuantityText(event.target.value)}
            onBlur={() => setQuantityText(String(parseQuantity(quantityText)))}
            className="h-11 w-24 rounded-md border border-input bg-background px-3 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <Button
          type="button"
          size="lg"
          variant="accent"
          onClick={handleAdd}
          aria-disabled={isBlocked}
          className="flex-1 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 sm:flex-none"
        >
          Add to basket
        </Button>
      </div>

      <p role="status" aria-live="polite" className="min-h-6 text-sm">
        {status.kind === 'adding' ? 'Adding to your basket…' : null}
        {status.kind === 'added' ? (
          <>
            Added to your basket.{' '}
            <Link href="/basket" className="font-medium underline underline-offset-4">
              View basket
            </Link>
          </>
        ) : null}
        {status.kind === 'error' ? <span className="text-destructive">{status.message}</span> : null}
      </p>
    </div>
  );
}
