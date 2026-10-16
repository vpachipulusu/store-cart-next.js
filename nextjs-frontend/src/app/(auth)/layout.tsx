import Link from 'next/link';
import type { ReactNode } from 'react';

/**
 * Auth shell (KAN-228). Below 760px: the form only, with a small brand link. From 760px: two columns,
 * an inverse brand panel (`--feature`) on the left and the form column on the right.
 * Each page supplies its own h1; the panel has no heading so there is exactly one per page.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground min-[760px]:grid min-[760px]:grid-cols-2">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-[60] focus:flex focus:min-h-11 focus:items-center focus:rounded-md focus:border focus:border-foreground focus:bg-background focus:px-4 focus:font-medium focus:text-foreground"
      >
        Skip to main content
      </a>
      <aside
        aria-label="About StoreCart"
        className="on-inverse hidden flex-col justify-between bg-feature p-12 text-background dark:text-foreground min-[760px]:flex"
      >
        <Link
          href="/"
          className="inline-flex min-h-11 items-center self-start rounded-md font-display text-2xl font-semibold"
        >
          StoreCart
        </Link>
        <div className="max-w-sm space-y-4">
          <p className="font-display text-4xl font-semibold leading-tight">Back to your shop.</p>
          <p className="text-base leading-relaxed">
            Products, orders and plan usage, kept in one tidy ledger for your store.
          </p>
        </div>
        <p className="text-sm">One workspace for every store you run.</p>
      </aside>
      <main
        id="main-content"
        className="flex items-center justify-center px-4 py-10 min-[760px]:px-12"
      >
        <div className="w-full max-w-[400px]">
          <Link
            href="/"
            className="mb-6 inline-flex min-h-11 items-center font-display text-xl font-semibold min-[760px]:hidden"
          >
            StoreCart
          </Link>
          {children}
        </div>
      </main>
    </div>
  );
}
