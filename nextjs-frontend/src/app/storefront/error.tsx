'use client';

import { StoreError } from '@/components/storefront/store-error';

/**
 * The store layout itself failed (the store lookup or category read threw). An error.tsx does not catch its own
 * segment's layout, so this one sits a level up, above `[slug]/layout.tsx`.
 */
export default function StoreLayoutError(props: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <StoreError {...props} />;
}
