import {
  CreditCard,
  LayoutDashboard,
  Package,
  Settings,
  Shield,
  Truck,
  User,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/**
 * The merchant dashboard nav (KAN-217). Only routes that exist have an entry; planned sections (Orders, Customers,
 * Domains) are added with their pages. Order is the sidebar order; the first TAB_COUNT items are the
 * phone tab bar and the rest go behind More.
 */
export const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { href: '/dashboard', label: 'Overview', icon: LayoutDashboard },
  { href: '/dashboard/products', label: 'Products', icon: Package },
  { href: '/dashboard/settings/billing', label: 'Billing', icon: CreditCard },
  { href: '/dashboard/settings/store', label: 'Shipping and tax', icon: Truck },
  { href: '/dashboard/settings', label: 'Settings', icon: Settings },
  { href: '/dashboard/profile', label: 'Profile', icon: User },
  { href: '/dashboard/security', label: 'Security', icon: Shield },
];

const TAB_COUNT = 3;

export const TAB_ITEMS: ReadonlyArray<NavItem> = NAV_ITEMS.slice(0, TAB_COUNT);
export const MORE_ITEMS: ReadonlyArray<NavItem> = NAV_ITEMS.slice(TAB_COUNT);

/**
 * The href of the nav item for the current path: the longest item href that equals the path or is a parent segment
 * of it. /dashboard matches only itself, so pages outside the nav (onboarding) have no current item.
 */
export function activeNavHref(pathname: string | null): string | null {
  if (!pathname) return null;
  let best: string | null = null;
  for (const { href } of NAV_ITEMS) {
    const matches = pathname === href || (href !== '/dashboard' && pathname.startsWith(`${href}/`));
    if (matches && (best === null || href.length > best.length)) best = href;
  }
  return best;
}
