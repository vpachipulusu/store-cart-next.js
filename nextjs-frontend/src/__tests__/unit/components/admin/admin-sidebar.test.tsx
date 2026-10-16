/** KAN-230: admin desktop sidebar landmarks, Admin label and current-page state. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

const mocks = vi.hoisted(() => ({ pathname: '/admin' }));
vi.mock('next/navigation', () => ({ usePathname: () => mocks.pathname }));

import { AdminSidebar } from '@/components/admin/admin-sidebar';
import { ADMIN_NAV_ITEMS } from '@/components/admin/admin-nav-items';

describe('AdminSidebar', () => {
  beforeEach(() => {
    mocks.pathname = '/admin';
  });

  it('is an aside named Workspace holding a nav named Main', () => {
    render(<AdminSidebar />);
    const aside = screen.getByRole('complementary', { name: 'Workspace' });
    expect(within(aside).getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  it('shows a visible Admin label in the switcher slot', () => {
    render(<AdminSidebar />);
    const aside = screen.getByRole('complementary', { name: 'Workspace' });
    expect(within(aside).getByText('Admin')).toBeVisible();
    expect(within(aside).queryByRole('link', { name: 'Admin' })).toBeNull();
  });

  it('lists every admin nav item as a link', () => {
    render(<AdminSidebar />);
    for (const item of ADMIN_NAV_ITEMS) {
      expect(screen.getByRole('link', { name: item.label })).toHaveAttribute('href', item.href);
    }
  });

  it('marks only the current page with aria-current', () => {
    mocks.pathname = '/admin/users/abc';
    render(<AdminSidebar />);
    const current = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'page');
    expect(current.map((link) => link.textContent)).toEqual(['Users']);
  });

  it('is hidden below 900px, uses the inverse panel, and has 44px targets', () => {
    render(<AdminSidebar />);
    const aside = screen.getByRole('complementary', { name: 'Workspace' });
    expect(aside.className).toContain('max-[899px]:hidden');
    expect(aside.className).toContain('bg-feature');
    expect(aside.className).toContain('on-inverse');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const link of within(nav).getAllByRole('link')) {
      expect(link.className).toContain('min-h-11');
    }
  });

  it('brand link returns to the admin home', () => {
    render(<AdminSidebar />);
    expect(screen.getByRole('link', { name: 'StoreCart' })).toHaveAttribute('href', '/admin');
  });
});
