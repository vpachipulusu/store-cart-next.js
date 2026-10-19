import { notFound } from 'next/navigation';

/**
 * Any other path on a store host (KAN-75): a 404 inside the store's header and footer (`[slug]/not-found.tsx`)
 * rather than the platform's. More specific routes (pages, `/cart` routes) always win over this catch-all.
 */

export const revalidate = 300;

export function generateStaticParams(): { rest: string[] }[] {
  return [];
}

export default function UnknownStorePath(): never {
  notFound();
}
