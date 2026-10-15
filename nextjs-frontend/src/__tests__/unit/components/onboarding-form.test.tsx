/** KAN-60: the onboarding form creates the organisation and first store, then goes to the status screen. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ createStoreAction: vi.fn(), push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('@/app/actions/onboarding-actions', () => ({ createStoreAction: mocks.createStoreAction }));

import { OnboardingForm } from '@/components/onboarding/onboarding-form';

describe('OnboardingForm', () => {
  beforeEach(() => vi.clearAllMocks());

  it('suggests addresses from the names and submits to the status screen', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm />);

    await user.type(screen.getByLabelText(/business name/i), 'Acme Ltd');
    await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
    expect(screen.getByLabelText(/business address/i)).toHaveValue('acme-ltd');
    expect(screen.getByLabelText(/store address/i)).toHaveValue('acme-shop');

    await user.click(screen.getByRole('button', { name: /create my store/i }));

    expect(mocks.createStoreAction).toHaveBeenCalledWith({
      organizationName: 'Acme Ltd',
      organizationSlug: 'acme-ltd',
      storeName: 'Acme Shop',
      storeSlug: 'acme-shop',
    });
    expect(mocks.push).toHaveBeenCalledWith('/dashboard/onboarding/status/st1');
  });

  it('keeps an address the user edited by hand', async () => {
    const user = userEvent.setup();
    render(<OnboardingForm />);
    const address = screen.getByLabelText(/store address/i);
    await user.type(address, 'my-own');
    await user.type(screen.getByLabelText(/store name/i), 'Other');
    expect(address).toHaveValue('my-own');
  });

  it('shows field errors from the server on the right field', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({
      success: false,
      fieldErrors: { storeSlug: 'That address is already taken. Choose another.' },
    });
    render(<OnboardingForm />);
    await user.type(screen.getByLabelText(/business name/i), 'Acme');
    await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
    await user.click(screen.getByRole('button', { name: /create my store/i }));

    expect(await screen.findByText(/already taken/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/store address/i)).toHaveAttribute('aria-invalid', 'true');
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it('shows a general error in an alert, and stays on the form so a retry resumes', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({
      success: false,
      error:
        'Your business was created but the store was not. Submit again to finish setting it up.',
    });
    render(<OnboardingForm />);
    await user.type(screen.getByLabelText(/business name/i), 'Acme');
    await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
    await user.click(screen.getByRole('button', { name: /create my store/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/business was created/i);
    expect(screen.getByRole('button', { name: /create my store/i })).toBeEnabled();
  });

  it('does not ask for a new business when one is already created', () => {
    render(<OnboardingForm resumeOrganizationName="Acme Ltd" />);
    expect(screen.queryByLabelText(/business name/i)).toBeNull();
    expect(screen.getByText(/acme ltd/i)).toBeInTheDocument();
  });

  it('submits the existing business name as a placeholder when resuming', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm resumeOrganizationName="Acme Ltd" />);
    await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
    await user.click(screen.getByRole('button', { name: /create my store/i }));
    expect(mocks.createStoreAction).toHaveBeenCalledWith(
      expect.objectContaining({ organizationName: 'Acme Ltd', storeSlug: 'acme-shop' })
    );
  });
});
