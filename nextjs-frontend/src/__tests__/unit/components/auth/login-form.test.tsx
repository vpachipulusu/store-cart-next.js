/** KAN-227: sign-in form states: alert panel, focus, loading and double submit. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { getFirebaseErrorMessage } from '@/lib/utils/firebase-errors';

const mocks = vi.hoisted(() => ({
  signInWithEmail: vi.fn(),
  verifyTokenAction: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock('@/lib/firebase/auth-helpers', () => ({ signInWithEmail: mocks.signInWithEmail }));
vi.mock('@/app/actions/auth-actions', () => ({ verifyTokenAction: mocks.verifyTokenAction }));

import { LoginForm } from '@/components/auth/login-form';

const fail = (code: string) => ({
  user: null,
  idToken: null,
  error: getFirebaseErrorMessage({ code }),
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/email/i), 'a@b.com');
  await user.type(screen.getByLabelText(/^password$/i), 'secret123');
  await user.click(screen.getByRole('button', { name: /sign in/i }));
}

describe('LoginForm', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it('moves focus to the first invalid field on submit', async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText(/^password$/i), 'secret123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    const email = screen.getByLabelText(/email/i);
    await waitFor(() => expect(email).toHaveFocus());
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(email).toHaveAccessibleDescription(/valid email/i);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each(['auth/user-not-found', 'auth/wrong-password'])(
    'shows the same neutral alert for %s and focuses it',
    async (code) => {
      const user = userEvent.setup();
      mocks.signInWithEmail.mockResolvedValue(fail(code));
      render(<LoginForm />);

      await fillAndSubmit(user);

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('We could not sign you in');
      expect(alert).toHaveTextContent(/email and password do not match/i);
      expect(alert).not.toHaveTextContent(/no account|not found|incorrect password/i);
      await waitFor(() => expect(alert).toHaveFocus());
    }
  );

  it('shows the network message', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValue(fail('auth/network-request-failed'));
    render(<LoginForm />);

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not reach storecart.*check your connection/i
    );
  });

  it('shows the rate limit message with the wait', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValue(fail('auth/too-many-requests'));
    render(<LoginForm />);

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/wait a few minutes/i);
  });

  it('shows the suspended message with a support link', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValue(fail('auth/user-disabled'));
    render(<LoginForm />);

    await fillAndSubmit(user);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This account is suspended');
    expect(screen.getByRole('link', { name: /contact support/i })).toHaveAttribute(
      'href',
      '/contact'
    );
  });

  it('hides the raw server refusal text', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValue({ user: {}, idToken: 't', error: null });
    mocks.verifyTokenAction.mockResolvedValue({
      success: false,
      error: 'Token verification failed',
    });
    render(<LoginForm />);

    await fillAndSubmit(user);

    const alert = await screen.findByRole('alert');
    expect(alert).not.toHaveTextContent(/token/i);
    expect(alert).toHaveTextContent(/try again/i);
  });

  it('treats a thrown error as a network problem', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockRejectedValue(new Error('offline'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<LoginForm />);

    await fillAndSubmit(user);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach storecart/i);
  });

  it('clears the alert on the next submit', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValueOnce(fail('auth/wrong-password'));
    mocks.signInWithEmail.mockReturnValueOnce(new Promise(() => {}));
    render(<LoginForm />);
    await fillAndSubmit(user);
    await screen.findByRole('alert');

    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('shows a loading label and submits once on a double submit', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockReturnValue(new Promise(() => {}));
    render(<LoginForm />);

    await fillAndSubmit(user);
    const button = await screen.findByRole('button', { name: /signing in/i });
    expect(button).toBeDisabled();
    await user.click(button);
    await user.keyboard('{Enter}');

    expect(mocks.signInWithEmail).toHaveBeenCalledTimes(1);
    expect(button.closest('form')).toHaveAttribute('aria-busy', 'true');
  });

  it('redirects to the dashboard on success', async () => {
    const user = userEvent.setup();
    mocks.signInWithEmail.mockResolvedValue({ user: {}, idToken: 't', error: null });
    mocks.verifyTokenAction.mockResolvedValue({ success: true });
    render(<LoginForm />);

    await fillAndSubmit(user);

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/dashboard'));
  });
});
