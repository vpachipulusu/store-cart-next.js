/** KAN-230: admin nav list and current-section matching. */
import { describe, expect, it } from 'vitest';
import { existsSync } from 'node:fs';
import path from 'node:path';
import {
  ADMIN_MORE_ITEMS,
  ADMIN_NAV_ITEMS,
  ADMIN_TAB_ITEMS,
  activeAdminHref,
} from '@/components/admin/admin-nav-items';

describe('admin nav items', () => {
  it('only links to admin routes that exist', () => {
    for (const { href } of ADMIN_NAV_ITEMS) {
      const dir = href === '/admin' ? '' : href.replace('/admin/', '');
      expect(
        existsSync(path.join(process.cwd(), 'src/app/(admin)/admin', dir, 'page.tsx')),
        href
      ).toBe(true);
    }
  });

  it('splits into the tab bar items and the More items without loss', () => {
    expect([...ADMIN_TAB_ITEMS, ...ADMIN_MORE_ITEMS]).toEqual(ADMIN_NAV_ITEMS);
    expect(ADMIN_TAB_ITEMS).toHaveLength(3);
  });

  it.each([
    ['/admin', '/admin'],
    ['/admin/users', '/admin/users'],
    ['/admin/users/abc', '/admin/users'],
    ['/admin/audit-logs', '/admin/audit-logs'],
    ['/admin/unknown', null],
    ['/dashboard', null],
    [null, null],
  ])('maps %s to %s', (pathname, expected) => {
    expect(activeAdminHref(pathname)).toBe(expected);
  });

  it('does not treat a sibling with a shared prefix as a child', () => {
    expect(activeAdminHref('/admin/users-archive')).toBeNull();
  });
});
