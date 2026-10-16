/** KAN-217: the nav lists only routes that exist and marks one current item. */
import { readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS, TAB_ITEMS, MORE_ITEMS, activeNavHref } from '@/components/dashboard/nav-items';

const DASHBOARD_DIR = path.resolve(__dirname, '../../../../app/dashboard');

function pageRoutes(dir: string, prefix: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return pageRoutes(full, `${prefix}/${name}`);
    return name === 'page.tsx' ? [prefix] : [];
  });
}

describe('nav items', () => {
  it('only links to routes that have a page', () => {
    const routes = pageRoutes(DASHBOARD_DIR, '/dashboard');
    for (const item of NAV_ITEMS) expect(routes).toContain(item.href);
  });

  it('splits into tab bar items and More items without losing or repeating any', () => {
    expect([...TAB_ITEMS, ...MORE_ITEMS].map((i) => i.href)).toEqual(NAV_ITEMS.map((i) => i.href));
    expect(TAB_ITEMS.length).toBeLessThanOrEqual(3);
  });
});

describe('activeNavHref', () => {
  it.each([
    ['/dashboard', '/dashboard'],
    ['/dashboard/profile', '/dashboard/profile'],
    ['/dashboard/settings', '/dashboard/settings'],
    ['/dashboard/settings/billing', '/dashboard/settings/billing'],
    ['/dashboard/security', '/dashboard/security'],
  ])('%s -> %s', (pathname, expected) => {
    expect(activeNavHref(pathname)).toBe(expected);
  });

  it('prefers the most specific item, so Settings is not current on the billing page', () => {
    expect(activeNavHref('/dashboard/settings/billing')).not.toBe('/dashboard/settings');
  });

  it('matches nested paths to their parent item', () => {
    expect(activeNavHref('/dashboard/profile/edit')).toBe('/dashboard/profile');
  });

  it('has no current item on unrelated or null paths', () => {
    expect(activeNavHref('/dashboard/onboarding')).toBeNull();
    expect(activeNavHref('/dashboard/profiles')).toBeNull();
    expect(activeNavHref(null)).toBeNull();
  });
});
