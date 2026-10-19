/** KAN-82, KAN-83: the shipping and tax form validates in the browser and saves minor units. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ updateStoreSettingsAction: vi.fn() }));
vi.mock('@/app/actions/store-settings-actions', () => ({
  updateStoreSettingsAction: mocks.updateStoreSettingsAction,
}));

import { StoreSettingsForm } from '@/components/dashboard/settings/store-settings-form';

const INITIAL = {
  shippingFlatRateMinor: 499,
  freeShippingThresholdMinor: 5000,
  taxRateBps: 725,
  pricesIncludeTax: false,
};

function renderForm() {
  return render(
    <StoreSettingsForm storeId="store1" initial={INITIAL} currency="GBP" exponent={2} />
  );
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.clearAllMocks();
});
afterEach(cleanup);

describe('StoreSettingsForm', () => {
  it('shows the saved values in major units and percent', () => {
    renderForm();

    expect(screen.getByLabelText(/Flat shipping rate/)).toHaveValue('4.99');
    expect(screen.getByLabelText(/Free shipping over/)).toHaveValue('50.00');
    expect(screen.getByLabelText(/Tax rate/)).toHaveValue('7.25');
    expect(screen.getByRole('switch', { name: 'Prices include tax' })).not.toBeChecked();
  });

  it('saves minor units, basis points and the switch', async () => {
    const user = userEvent.setup();
    mocks.updateStoreSettingsAction.mockResolvedValue({
      success: true,
      data: {
        shipping_flat_rate_minor: 599,
        free_shipping_threshold_minor: null,
        tax_rate_bps: 2000,
        prices_include_tax: true,
        updated_at: '',
      },
    });
    renderForm();

    await user.clear(screen.getByLabelText(/Flat shipping rate/));
    await user.type(screen.getByLabelText(/Flat shipping rate/), '5.99');
    await user.clear(screen.getByLabelText(/Free shipping over/));
    await user.clear(screen.getByLabelText(/Tax rate/));
    await user.type(screen.getByLabelText(/Tax rate/), '20');
    await user.click(screen.getByRole('switch', { name: 'Prices include tax' }));
    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() =>
      expect(mocks.updateStoreSettingsAction).toHaveBeenCalledWith({
        storeId: 'store1',
        shippingFlatRateMinor: 599,
        freeShippingThresholdMinor: null,
        taxRateBps: 2000,
        pricesIncludeTax: true,
      })
    );
    expect(await screen.findByRole('status')).toHaveTextContent('Settings saved.');
  });

  it('shows field errors and does not call the server for invalid input', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.clear(screen.getByLabelText(/Tax rate/));
    await user.type(screen.getByLabelText(/Tax rate/), '150');
    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(await screen.findByText(/percentage from 0 to 100/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Tax rate/)).toHaveFocus();
    expect(screen.queryByText('Check the highlighted fields and try again.')).toBeNull();
    expect(mocks.updateStoreSettingsAction).not.toHaveBeenCalled();
  });

  it('accepts a comma as the decimal separator', async () => {
    const user = userEvent.setup();
    mocks.updateStoreSettingsAction.mockResolvedValue({ success: false, error: 'x' });
    renderForm();

    await user.clear(screen.getByLabelText(/Tax rate/));
    await user.type(screen.getByLabelText(/Tax rate/), '7,5');
    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() =>
      expect(mocks.updateStoreSettingsAction).toHaveBeenCalledWith(
        expect.objectContaining({ taxRateBps: 750 })
      )
    );
  });

  it('clears the saved message as soon as a field changes', async () => {
    const user = userEvent.setup();
    mocks.updateStoreSettingsAction.mockResolvedValue({
      success: true,
      data: {
        shipping_flat_rate_minor: 499,
        free_shipping_threshold_minor: 5000,
        tax_rate_bps: 725,
        prices_include_tax: false,
        updated_at: '',
      },
    });
    renderForm();

    await user.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Tax rate/), '1');

    expect(screen.queryByText('Settings saved.')).toBeNull();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('shows the action error', async () => {
    const user = userEvent.setup();
    mocks.updateStoreSettingsAction.mockResolvedValue({ success: false, error: 'No permission.' });
    renderForm();

    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(await screen.findByText('No permission.')).toBeInTheDocument();
  });

  it('shows a fixed message when the action throws', async () => {
    const user = userEvent.setup();
    mocks.updateStoreSettingsAction.mockRejectedValue(new Error('boom'));
    renderForm();

    await user.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(await screen.findByText('The request failed. Please try again.')).toBeInTheDocument();
  });

  it('keeps focus on the save button while saving', async () => {
    const user = userEvent.setup();
    let finish: (value: unknown) => void = () => {};
    mocks.updateStoreSettingsAction.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderForm();
    const save = screen.getByRole('button', { name: 'Save settings' });

    await user.click(save);

    expect(await screen.findByRole('button', { name: 'Saving…' })).toHaveFocus();
    finish({ success: false, error: 'No permission.' });
  });
});
