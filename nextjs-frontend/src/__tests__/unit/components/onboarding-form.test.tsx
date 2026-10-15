/** KAN-60: the onboarding form creates the organisation and first store, then goes to the status screen. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ createStoreAction: vi.fn(), push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('@/app/actions/onboarding-actions', () => ({ createStoreAction: mocks.createStoreAction }));

import { OnboardingForm, PUSH_STALL_MS } from '@/components/onboarding/onboarding-form';
import { SESSION_EXPIRED_MESSAGE } from '@/lib/onboarding/schema';

const submitButton = () => screen.getByRole('button', { name: /create my store|creating/i });

async function fillNew(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/business name/i), 'Acme Ltd');
  await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
}

describe('OnboardingForm', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('suggests addresses from the names and submits to the status screen', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm />);

    await fillNew(user);
    expect(screen.getByLabelText(/business address/i)).toHaveValue('acme-ltd');
    expect(screen.getByLabelText(/store address/i)).toHaveValue('acme-shop');

    await user.click(submitButton());

    expect(mocks.createStoreAction).toHaveBeenCalledWith({
      mode: 'new',
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

  it('submits only once when the form is submitted twice before the first call returns', async () => {
    const user = userEvent.setup();
    let resolve: (value: unknown) => void = () => {};
    mocks.createStoreAction.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<OnboardingForm />);
    await fillNew(user);

    const form = submitButton().closest('form') as HTMLFormElement;
    await act(async () => {
      form.requestSubmit();
      form.requestSubmit();
    });
    expect(mocks.createStoreAction).toHaveBeenCalledTimes(1);
    expect(submitButton()).toHaveAttribute('aria-disabled', 'true');
    expect(submitButton()).not.toBeDisabled();

    await act(async () => resolve({ success: true, data: { storeId: 'st1' } }));
  });

  it('shows server field errors on the right field and focuses the first invalid one', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({
      success: false,
      fieldErrors: { storeSlug: 'That address is already taken. Choose another.' },
    });
    render(<OnboardingForm />);
    await fillNew(user);
    await user.click(submitButton());

    expect(await screen.findByText(/already taken/i)).toBeInTheDocument();
    const address = screen.getByLabelText(/store address/i);
    expect(address).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(address).toHaveFocus());
    expect(mocks.push).not.toHaveBeenCalled();
    expect(submitButton()).toHaveAttribute('aria-disabled', 'false');
  });

  it('switches to resume mode when the business was created but the store was not, keeping the typed values', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction
      .mockResolvedValueOnce({
        success: false,
        error:
          'Your business was created but the store was not. Submit again to finish setting it up.',
        organizationCreated: true,
      })
      .mockResolvedValueOnce({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm />);
    await fillNew(user);
    await user.click(submitButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(/business was created/i);
    expect(screen.queryByLabelText(/business name/i)).toBeNull();
    expect(screen.getByText(/acme ltd/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/store name/i)).toHaveValue('Acme Shop');

    await user.click(submitButton());
    expect(mocks.createStoreAction).toHaveBeenLastCalledWith({
      mode: 'resume',
      storeName: 'Acme Shop',
      storeSlug: 'acme-shop',
    });
  });

  it('shows a general error in an alert and leaves the form usable', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({
      success: false,
      error: 'Your plan does not allow another store.',
    });
    render(<OnboardingForm />);
    await fillNew(user);
    await user.click(submitButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(/plan does not allow/i);
    expect(submitButton()).toHaveAttribute('aria-disabled', 'false');
  });

  it('maps the unauthorized code to session text and never shows the bare word Unauthorized', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({ success: false, code: 'unauthorized' });
    render(<OnboardingForm />);
    await fillNew(user);
    await user.click(submitButton());

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(SESSION_EXPIRED_MESSAGE);
    expect(alert).not.toHaveTextContent(/^unauthorized$/i);
  });

  it('re-enables the button if the navigation to the status screen stalls', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.createStoreAction.mockResolvedValue({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await fillNew(user);
    await user.click(submitButton());

    expect(mocks.push).toHaveBeenCalled();
    expect(submitButton()).toHaveAttribute('aria-disabled', 'true');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PUSH_STALL_MS);
    });
    expect(submitButton()).toHaveAttribute('aria-disabled', 'false');
  });

  it('does not ask for a new business when one is already created', () => {
    render(<OnboardingForm resumeOrganizationName="Acme Ltd" />);
    expect(screen.queryByLabelText(/business name/i)).toBeNull();
    expect(screen.getByText(/acme ltd/i)).toBeInTheDocument();
  });

  it('submits a store-only resume request when resuming', async () => {
    const user = userEvent.setup();
    mocks.createStoreAction.mockResolvedValue({ success: true, data: { storeId: 'st1' } });
    render(<OnboardingForm resumeOrganizationName="Acme Ltd" />);
    await user.type(screen.getByLabelText(/store name/i), 'Acme Shop');
    await user.click(submitButton());
    expect(mocks.createStoreAction).toHaveBeenCalledWith({
      mode: 'resume',
      storeName: 'Acme Shop',
      storeSlug: 'acme-shop',
    });
  });
});
