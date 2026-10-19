'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShoppingBag } from 'lucide-react';
import { CART_CHANGED_EVENT, itemCount, readCart, type Cart } from '@/lib/storefront/cart-client';

/** Header basket link with the item count, read from this store's cart after the (cached) page loads. */
export function CartCount() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let isActive = true;
    // A change event carries a newer cart than a first read still in flight.
    let hasNewer = false;
    void readCart().then((reply) => {
      if (isActive && !hasNewer && reply.ok) setCount(itemCount(reply.cart));
    });
    const handleChange = (event: Event) => {
      const cart = (event as CustomEvent<Cart>).detail;
      if (!cart) return;
      hasNewer = true;
      setCount(itemCount(cart));
    };
    window.addEventListener(CART_CHANGED_EVENT, handleChange);
    return () => {
      isActive = false;
      window.removeEventListener(CART_CHANGED_EVENT, handleChange);
    };
  }, []);

  const label = count ? `Basket, ${count} ${count === 1 ? 'item' : 'items'}` : 'Basket';
  return (
    <Link
      href="/basket"
      aria-label={label}
      className="relative inline-flex h-11 min-w-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <ShoppingBag className="h-5 w-5" aria-hidden="true" />
      <span className="hidden sm:inline">Basket</span>
      {count ? (
        <span
          aria-hidden="true"
          className="rounded-full bg-primary px-2 py-0.5 text-xs font-semibold tabular-nums text-primary-foreground"
        >
          {count}
        </span>
      ) : null}
    </Link>
  );
}
