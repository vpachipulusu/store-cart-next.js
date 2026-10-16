/** KAN-218: a 52px slot; a label for one store, a "Switch store" menu for several; a failed switch toasts. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({
  selectStoreAction: vi.fn(),
  refresh: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('@/app/actions/store-actions', () => ({ selectStoreAction: mocks.selectStoreAction }));

import { StoreSwitcher } from '@/components/dashboard/store-switcher';
import type { MerchantStore } from '@/lib/stores/selection';

const store = (id: string, name: string, organizationName = 'Org'): MerchantStore => ({
  id,
  name,
  slug: name.toLowerCase(),
  status: 'ACTIVE',
  organizationId: 'o1',
  organizationName,
});
const ONE = store('tz4a98xxat96iws9zmbrgj3a', 'Alpha', 'Acme Ltd');
const TWO = store('pfh0haxfpzowht3oi213cqos', 'Beta', 'Bravo Inc');

describe('StoreSwitcher', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.selectStoreAction.mockResolvedValue({ success: true });
    // Radix menus need these in jsdom.
    Element.prototype.hasPointerCapture = () => false;
    Element.prototype.scrollIntoView = () => {};
  });

  describe('one store', () => {
    it('is a non-interactive label with the store name and organisation', () => {
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);
      const label = screen.getByTestId('store-name');
      expect(label).toHaveTextContent('Alpha');
      expect(label).toHaveTextContent('Acme Ltd');
      expect(screen.getByRole('group', { name: 'Current store' })).toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      expect(screen.queryByTestId('store-switcher')).not.toBeInTheDocument();
    });

    it('fills the 52px slot', () => {
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);
      expect(screen.getByTestId('store-name').className).toContain('h-[52px]');
    });
  });

  describe('several stores', () => {
    it('has a 52px menu trigger named "Switch store" showing store, organisation and a chevron', () => {
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={TWO.id} />);
      const trigger = screen.getByRole('button', { name: 'Switch store' });
      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(trigger.className).toContain('h-[52px]');
      expect(trigger).toHaveTextContent('Beta');
      expect(trigger).toHaveTextContent('Bravo Inc');
      expect(trigger.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    });

    it('falls back to the first store when the selected id is unknown', () => {
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId="missing" />);
      expect(screen.getByRole('button', { name: 'Switch store' })).toHaveTextContent('Alpha');
    });

    it('opens a menu of 44px radio items with the current store checked', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: 'Switch store' }));

      const menu = await screen.findByRole('menu');
      const items = within(menu).getAllByRole('menuitemradio');
      expect(items).toHaveLength(2);
      expect(items[0]).toHaveAttribute('aria-checked', 'true');
      expect(items[1]).toHaveAttribute('aria-checked', 'false');
      for (const item of items) expect(item.className).toContain('min-h-11');
      expect(items[1]).toHaveTextContent('Bravo Inc');
    });

    it('switches store through the server action and refreshes', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: 'Switch store' }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Beta/ }));

      expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id);
      await vi.waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
      expect(mocks.toast).not.toHaveBeenCalled();
    });

    it('does nothing when the current store is picked again', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: 'Switch store' }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Alpha/ }));

      expect(mocks.selectStoreAction).not.toHaveBeenCalled();
    });

    it('is operable from the keyboard', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.tab();
      expect(screen.getByRole('button', { name: 'Switch store' })).toHaveFocus();
      await user.keyboard('{Enter}');
      await screen.findByRole('menu');
      await user.keyboard('{ArrowDown}{Enter}');

      await vi.waitFor(() => expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id));
    });

    it('closes the menu with Escape and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);
      const trigger = screen.getByRole('button', { name: 'Switch store' });

      await user.click(trigger);
      await screen.findByRole('menu');
      await user.keyboard('{Escape}');

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it('still shows a toast and does not refresh when the switch fails', async () => {
      mocks.selectStoreAction.mockResolvedValue({ success: false, error: 'nope' });
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: 'Switch store' }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Beta/ }));

      await vi.waitFor(() =>
        expect(mocks.toast).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Could not switch store',
            description: 'nope',
            variant: 'destructive',
          })
        )
      );
      expect(mocks.refresh).not.toHaveBeenCalled();
    });

    it('shows a toast when the action itself throws', async () => {
      mocks.selectStoreAction.mockRejectedValue(new Error('network'));
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: 'Switch store' }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Beta/ }));

      await vi.waitFor(() =>
        expect(mocks.toast).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Could not switch store', variant: 'destructive' })
        )
      );
      expect(mocks.refresh).not.toHaveBeenCalled();
    });
  });

  describe('sidebar variant', () => {
    it('uses inverse-surface colours that work in light and dark', () => {
      render(<StoreSwitcher variant="sidebar" stores={[ONE, TWO]} selectedStoreId={ONE.id} />);
      const trigger = screen.getByRole('button', { name: 'Switch store' });
      expect(trigger.className).toContain('text-background');
      expect(trigger.className).toContain('dark:text-foreground');
      expect(trigger.className).toContain('w-full');
    });

    it('keeps the single-store label inverse too', () => {
      render(<StoreSwitcher variant="sidebar" stores={[ONE]} selectedStoreId={ONE.id} />);
      expect(screen.getByTestId('store-name').className).toContain('text-background');
    });
  });

  it('renders nothing without stores', () => {
    const { container } = render(<StoreSwitcher stores={[]} selectedStoreId="x" />);
    expect(container).toBeEmptyDOMElement();
  });
});
