'use client';

import { StoreError } from '@/components/storefront/store-error';

/** A store page failed inside a working store layout: the header and footer stay. */
export default function StorePageError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <StoreError {...props} />;
}
