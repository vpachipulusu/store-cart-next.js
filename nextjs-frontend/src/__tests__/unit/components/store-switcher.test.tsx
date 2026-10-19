/**
 * KAN-218: a 52px "Switch store" menu; a failed switch toasts. KAN-254: the menu exists for one store too and
 * always ends with "New store", which opens the create-store dialog.
 */
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
vi.mock('@/app/actions/onboarding-actions', () => ({
  createAdditionalStoreAction: vi.fn(),
  getStoreStatusAction: vi.fn(),
  retryProvisioningAction: vi.fn(),
}));

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
    it('is a 52px "Switch store" menu trigger showing the store and organisation', () => {
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);
      const trigger = screen.getByRole('button', { name: 'Switch store, current Alpha, Acme Ltd' });
      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('data-testid', 'store-switcher');
      expect(trigger.className).toContain('h-[52px]');
      expect(trigger).toHaveTextContent('Alpha');
      expect(trigger).toHaveTextContent('Acme Ltd');
    });

    it('lists the store (checked) and a 44px "New store" item', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));

      const menu = await screen.findByRole('menu');
      const stores = within(menu).getAllByRole('menuitemradio');
      expect(stores).toHaveLength(1);
      expect(stores[0]).toHaveAttribute('aria-checked', 'true');
      const newStore = within(menu).getByRole('menuitem', { name: 'New store' });
      expect(newStore.className).toContain('min-h-11');
    });

    it('opens the New store dialog from the menu and closes the menu', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));
      await user.click(await screen.findByRole('menuitem', { name: 'New store' }));

      expect(await screen.findByRole('dialog', { name: 'New store' })).toBeInTheDocument();
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(screen.getByLabelText(/store name/i)).toBeInTheDocument();
      expect(mocks.selectStoreAction).not.toHaveBeenCalled();
    });

    it('opens the dialog from the keyboard and returns focus to the trigger when it closes', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);
      const trigger = screen.getByRole('button', { name: /switch store/i });

      await user.tab();
      expect(trigger).toHaveFocus();
      await user.keyboard('{Enter}');
      await screen.findByRole('menu');
      await user.keyboard('{ArrowDown}{Enter}');
      await screen.findByRole('dialog', { name: 'New store' });

      await user.keyboard('{Escape}');

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      await vi.waitFor(() => expect(trigger).toHaveFocus());
    });
  });

  describe('several stores', () => {
    it('has a 52px menu trigger named "Switch store" showing store, organisation and a chevron', () => {
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={TWO.id} />);
      const trigger = screen.getByRole('button', { name: /switch store/i });
      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(trigger.className).toContain('h-[52px]');
      expect(trigger).toHaveTextContent('Beta');
      expect(trigger).toHaveTextContent('Bravo Inc');
      expect(trigger.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    });

    it('names the trigger with the current store and organisation (label in name)', () => {
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={TWO.id} />);
      expect(
        screen.getByRole('button', { name: 'Switch store, current Beta, Bravo Inc' })
      ).toBeInTheDocument();
    });

    it('announces and shows a pending state, and ignores a second pick, while switching', async () => {
      let finish: (value: { success: boolean }) => void = () => {};
      mocks.selectStoreAction.mockReturnValue(new Promise((resolve) => (finish = resolve)));
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Beta/ }));

      await vi.waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent('Switching store')
      );
      const trigger = screen.getByRole('button', { name: /switch store/i });
      expect(trigger).toHaveAttribute('aria-busy', 'true');
      expect(trigger.querySelector('svg.animate-spin')).not.toBeNull();
      expect(mocks.selectStoreAction).toHaveBeenCalledTimes(1);

      await user.click(trigger);
      for (const item of await screen.findAllByRole('menuitemradio')) {
        expect(item).toHaveAttribute('aria-disabled', 'true');
      }

      finish({ success: true });
      await vi.waitFor(() => expect(screen.getByRole('status')).toBeEmptyDOMElement());
    });

    it('falls back to the first store when the selected id is unknown', () => {
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId="missing" />);
      expect(screen.getByRole('button', { name: /switch store/i })).toHaveTextContent('Alpha');
    });

    it('opens a menu of 44px radio items with the current store checked', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));

      const menu = await screen.findByRole('menu');
      const items = within(menu).getAllByRole('menuitemradio');
      expect(items).toHaveLength(2);
      expect(within(menu).getByRole('menuitem', { name: 'New store' })).toBeInTheDocument();
      expect(items[0]).toHaveAttribute('aria-checked', 'true');
      expect(items[1]).toHaveAttribute('aria-checked', 'false');
      for (const item of items) expect(item.className).toContain('min-h-11');
      expect(items[1]).toHaveTextContent('Bravo Inc');
    });

    it('switches store through the server action and refreshes', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Beta/ }));

      expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id);
      await vi.waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
      expect(mocks.toast).not.toHaveBeenCalled();
    });

    it('does nothing when the current store is picked again', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.click(screen.getByRole('button', { name: /switch store/i }));
      await user.click(await screen.findByRole('menuitemradio', { name: /Alpha/ }));

      expect(mocks.selectStoreAction).not.toHaveBeenCalled();
    });

    it('is operable from the keyboard', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

      await user.tab();
      expect(screen.getByRole('button', { name: /switch store/i })).toHaveFocus();
      await user.keyboard('{Enter}');
      await screen.findByRole('menu');
      await user.keyboard('{ArrowDown}{Enter}');

      await vi.waitFor(() => expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id));
    });

    it('closes the menu with Escape and returns focus to the trigger', async () => {
      const user = userEvent.setup();
      render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);
      const trigger = screen.getByRole('button', { name: /switch store/i });

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

      await user.click(screen.getByRole('button', { name: /switch store/i }));
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

      await user.click(screen.getByRole('button', { name: /switch store/i }));
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
      const trigger = screen.getByRole('button', { name: /switch store/i });
      expect(trigger.className).toContain('text-background');
      expect(trigger.className).toContain('dark:text-foreground');
      expect(trigger.className).toContain('w-full');
    });

    it('keeps the single-store menu trigger inverse too', () => {
      render(<StoreSwitcher variant="sidebar" stores={[ONE]} selectedStoreId={ONE.id} />);
      expect(screen.getByTestId('store-switcher').className).toContain('text-background');
    });
  });

  it('renders nothing without stores', () => {
    const { container } = render(<StoreSwitcher stores={[]} selectedStoreId="x" />);
    expect(container).toBeEmptyDOMElement();
  });
});
