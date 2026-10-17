/** KAN-240: an outage during OAuth sign-in is not reported as a refused sign-in. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SIGN_IN_SERVICE_UNAVAILABLE_ERROR } from '@/lib/auth/auth-error-messages';

const mocks = vi.hoisted(() => ({
  toast: vi.fn(),
  verifyTokenAction: vi.fn(),
  signInWithGoogle: vi.fn(),
  signInWithGitHub: vi.fn(),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mocks.toast }) }));
vi.mock('@/app/actions/auth-actions', () => ({ verifyTokenAction: mocks.verifyTokenAction }));
vi.mock('@/lib/firebase/auth-helpers', () => ({
  signInWithGoogle: mocks.signInWithGoogle,
  signInWithGitHub: mocks.signInWithGitHub,
}));

import { OAuthButtons } from '@/components/auth/oauth-buttons';

describe('OAuthButtons verification failures', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.signInWithGoogle.mockResolvedValue({ user: { uid: 'u' }, idToken: 'tok' });
    mocks.signInWithGitHub.mockResolvedValue({ user: { uid: 'u' }, idToken: 'tok' });
  });

  it.each(['Google', 'GitHub'])(
    '%s names a service outage instead of "Authentication Failed"',
    async (provider) => {
      mocks.verifyTokenAction.mockResolvedValue({
        success: false,
        error: SIGN_IN_SERVICE_UNAVAILABLE_ERROR,
        data: { serviceUnavailable: true },
      });
      render(<OAuthButtons />);

      fireEvent.click(screen.getByRole('button', { name: new RegExp(provider, 'i') }));

      await waitFor(() => expect(mocks.toast).toHaveBeenCalled());
      const toast = mocks.toast.mock.calls[0][0];
      expect(toast.title).toBe('Sign-in is unavailable right now');
      expect(JSON.stringify(toast)).not.toMatch(/Authentication Failed|token/i);
    }
  );

  it.each(['Google', 'GitHub'])(
    '%s does not treat the outage text without the typed flag as an outage',
    async (provider) => {
      mocks.verifyTokenAction.mockResolvedValue({
        success: false,
        error: SIGN_IN_SERVICE_UNAVAILABLE_ERROR,
      });
      render(<OAuthButtons />);

      fireEvent.click(screen.getByRole('button', { name: new RegExp(provider, 'i') }));

      await waitFor(() => expect(mocks.toast).toHaveBeenCalled());
      expect(mocks.toast.mock.calls[0][0].title).toBe('Authentication Failed');
    }
  );

  it('keeps "Authentication Failed" when the token is refused', async () => {
    mocks.verifyTokenAction.mockResolvedValue({
      success: false,
      error: 'Token verification failed',
    });
    render(<OAuthButtons />);

    fireEvent.click(screen.getByRole('button', { name: /google/i }));

    await waitFor(() => expect(mocks.toast).toHaveBeenCalled());
    expect(mocks.toast.mock.calls[0][0].title).toBe('Authentication Failed');
  });
});
