import {
  BarChart3,
  Building2,
  CreditCard,
  FileText,
  LayoutDashboard,
  Search,
  Settings,
  Store,
  Users,
  type LucideIcon,
} from 'lucide-react';

export interface AdminNavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/**
 * The admin nav (KAN-230). Only routes that exist have an entry. Order is the sidebar order; the first
 * TAB_COUNT items are the phone tab bar and the rest go behind More.
 */
export const ADMIN_NAV_ITEMS: ReadonlyArray<AdminNavItem> = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/users', label: 'Users', icon: Users },
  { href: '/admin/subscriptions', label: 'Subscriptions', icon: CreditCard },
  { href: '/admin/organizations', label: 'Organisations', icon: Building2 },
  { href: '/admin/stores', label: 'Stores', icon: Store },
  { href: '/admin/analytics', label: 'Analytics', icon: BarChart3 },
  { href: '/admin/seo', label: 'SEO', icon: Search },
  { href: '/admin/settings', label: 'Settings', icon: Settings },
  { href: '/admin/audit-logs', label: 'Audit Logs', icon: FileText },
];

const TAB_COUNT = 3;

export const ADMIN_TAB_ITEMS: ReadonlyArray<AdminNavItem> = ADMIN_NAV_ITEMS.slice(0, TAB_COUNT);
export const ADMIN_MORE_ITEMS: ReadonlyArray<AdminNavItem> = ADMIN_NAV_ITEMS.slice(TAB_COUNT);

/**
 * The href of the nav item for the current path: the longest item href that equals the path or is a parent segment
 * of it. /admin matches only itself, so unknown paths have no current item.
 */
export function activeAdminHref(pathname: string | null): string | null {
  if (!pathname) return null;
  let best: string | null = null;
  for (const { href } of ADMIN_NAV_ITEMS) {
    const matches = pathname === href || (href !== '/admin' && pathname.startsWith(`${href}/`));
    if (matches && (best === null || href.length > best.length)) best = href;
  }
  return best;
}
