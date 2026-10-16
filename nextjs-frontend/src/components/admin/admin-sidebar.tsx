'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { ADMIN_NAV_ITEMS, activeAdminHref } from './admin-nav-items';

/**
 * Admin desktop navigation (KAN-230): the same 240px inverse panel as the merchant sidebar, with a visible "Admin"
 * label where the store switcher sits so the context is unmistakable. Below 900px the AdminTabBar takes over.
 * It only renders navigation; admin access is verified server-side by the layout and each page.
 */
export function AdminSidebar() {
  const current = activeAdminHref(usePathname());

  return (
    <aside
      aria-label="Workspace"
      className="on-inverse fixed inset-y-0 start-0 z-40 flex w-60 flex-col gap-6 overflow-y-auto bg-feature px-3 py-4 text-background dark:text-foreground max-[899px]:hidden"
    >
      <Link
        href="/admin"
        className="flex min-h-11 items-center rounded-md px-3 font-display text-xl font-semibold"
      >
        StoreCart
      </Link>
      <div className="flex min-h-[52px] items-center gap-2 rounded-md border border-background/20 px-3 text-sm font-semibold dark:border-foreground/20">
        <span className="rounded-sm bg-background/15 px-1.5 py-0.5 text-xs uppercase tracking-wide dark:bg-foreground/15">
          Admin
        </span>
      </div>
      <nav aria-label="Main">
        <ul className="flex flex-col gap-1">
          {ADMIN_NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const isCurrent = href === current;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={isCurrent ? 'page' : undefined}
                  className={cn(
                    'relative flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                    'text-background/75 hover:bg-background/10 hover:text-background',
                    'dark:text-foreground/75 dark:hover:bg-foreground/10 dark:hover:text-foreground',
                    isCurrent &&
                      'bg-background/15 text-background before:absolute before:inset-y-1 before:start-0 before:w-[3px] before:rounded-full before:bg-cta dark:bg-foreground/15 dark:text-foreground'
                  )}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
