/** KAN-79: the manual fulfilment form validates, submits once, and shows curated failures. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), fulfilOrderAction: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock('@/app/actions/order-actions', () => ({ fulfilOrderAction: mocks.fulfilOrderAction }));

import { FulfilForm } from '@/components/dashboard/orders/fulfil-form';

const ORDER = 'order1';

async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^Mark as fulfilled|Marking/ }));
}

describe('FulfilForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fulfilOrderAction.mockResolvedValue({ success: true, data: { id: ORDER } });
  });

  it('rejects an empty tracking number without calling the action', async () => {
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);

    await submit(user);

    expect(screen.getAllByRole('alert').map((node) => node.textContent)).toContain(
      'Tracking number is required'
    );
    expect(mocks.fulfilOrderAction).not.toHaveBeenCalled();
  });

  it('sends the typed values and refreshes the page on success', async () => {
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);

    await user.type(screen.getByLabelText('Tracking number'), 'RM1');
    await user.type(screen.getByLabelText('Carrier (optional)'), 'Royal Mail');
    await submit(user);

    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1));
    expect(mocks.fulfilOrderAction).toHaveBeenCalledWith(ORDER, {
      trackingNumber: 'RM1',
      carrier: 'Royal Mail',
    });
  });

  it('does not call the action a second time after success', async () => {
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);
    await user.type(screen.getByLabelText('Tracking number'), 'RM1');

    await submit(user);
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
    await user.keyboard('{Enter}');

    expect(mocks.fulfilOrderAction).toHaveBeenCalledTimes(1);
  });

  it('shows the curated server message and allows another try', async () => {
    mocks.fulfilOrderAction.mockResolvedValueOnce({
      success: false,
      error: 'Only a paid order can be fulfilled',
    });
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);
    await user.type(screen.getByLabelText('Tracking number'), 'RM1');

    await submit(user);

    expect(await screen.findByText('Only a paid order can be fulfilled')).toBeInTheDocument();
    expect(mocks.refresh).not.toHaveBeenCalled();
    await submit(user);
    expect(mocks.fulfilOrderAction).toHaveBeenCalledTimes(2);
  });

  it('shows server field errors next to the field', async () => {
    mocks.fulfilOrderAction.mockResolvedValueOnce({
      success: false,
      error: 'Check the highlighted fields and try again.',
      fieldErrors: { trackingNumber: 'Tracking number contains invalid characters' },
    });
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);
    await user.type(screen.getByLabelText('Tracking number'), 'RM1');

    await submit(user);

    expect(
      await screen.findByText('Tracking number contains invalid characters')
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Tracking number')).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows a fixed message when the action throws', async () => {
    mocks.fulfilOrderAction.mockRejectedValueOnce(new Error('network down'));
    const user = userEvent.setup();
    render(<FulfilForm orderId={ORDER} />);
    await user.type(screen.getByLabelText('Tracking number'), 'RM1');

    await submit(user);

    expect(await screen.findByText('The request failed. Please try again.')).toBeInTheDocument();
    expect(screen.queryByText('network down')).not.toBeInTheDocument();
  });
});
