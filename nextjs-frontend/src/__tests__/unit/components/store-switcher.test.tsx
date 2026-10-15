/** KAN-61: the switcher is hidden chrome for one store, an accessible 44px select for several. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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

const store = (id: string, name: string): MerchantStore => ({
  id,
  name,
  slug: name.toLowerCase(),
  status: 'ACTIVE',
  organizationId: 'o1',
  organizationName: 'Org',
});
const ONE = store('tz4a98xxat96iws9zmbrgj3a', 'Alpha');
const TWO = store('pfh0haxfpzowht3oi213cqos', 'Beta');

describe('StoreSwitcher', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.selectStoreAction.mockResolvedValue({ success: true });
    // Radix Select needs these in jsdom.
    Element.prototype.hasPointerCapture = () => false;
    Element.prototype.scrollIntoView = () => {};
  });

  it('shows only the store name, with no switcher, for one store', () => {
    render(<StoreSwitcher stores={[ONE]} selectedStoreId={ONE.id} />);
    expect(screen.getByTestId('store-name')).toHaveTextContent('Alpha');
    expect(screen.getByRole('group', { name: 'Current store' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('renders a labelled 44px combobox showing the selected store for several stores', () => {
    render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={TWO.id} />);
    const trigger = screen.getByRole('combobox', { name: 'Switch store' });
    expect(trigger).toHaveTextContent('Beta');
    expect(trigger.className).toContain('h-11');
  });

  it('switches store through the server action and refreshes', async () => {
    const user = userEvent.setup();
    render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

    await user.click(screen.getByRole('combobox', { name: 'Switch store' }));
    await user.click(await screen.findByRole('option', { name: /Beta/ }));

    expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id);
    await vi.waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
  });

  it('is operable from the keyboard', async () => {
    const user = userEvent.setup();
    render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

    await user.tab();
    expect(screen.getByRole('combobox', { name: 'Switch store' })).toHaveFocus();
    await user.keyboard('{Enter}');
    await user.keyboard('{ArrowDown}{Enter}');

    await vi.waitFor(() => expect(mocks.selectStoreAction).toHaveBeenCalledWith(TWO.id));
  });

  it('reports a failed switch and does not refresh', async () => {
    mocks.selectStoreAction.mockResolvedValue({ success: false, error: 'nope' });
    const user = userEvent.setup();
    render(<StoreSwitcher stores={[ONE, TWO]} selectedStoreId={ONE.id} />);

    await user.click(screen.getByRole('combobox', { name: 'Switch store' }));
    await user.click(await screen.findByRole('option', { name: /Beta/ }));

    await vi.waitFor(() => expect(mocks.toast).toHaveBeenCalled());
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});
