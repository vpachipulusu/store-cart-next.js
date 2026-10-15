import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  refreshSessionAction: vi.fn(),
  signOut: vi.fn(),
  idTokenListener: null as null | ((user: unknown) => Promise<void>),
}));

vi.mock('@/app/actions/auth-actions', () => ({ refreshSessionAction: mocks.refreshSessionAction }));
vi.mock('@/lib/firebase/client', () => ({ auth: { currentUser: null } }));
vi.mock('firebase/auth', () => ({
  signOut: mocks.signOut,
  onIdTokenChanged: (_auth: unknown, listener: (user: unknown) => Promise<void>) => {
    mocks.idTokenListener = listener;
    return vi.fn();
  },
}));

import { useSessionRefresh } from '@/hooks/use-session-refresh';

const USER = { getIdToken: vi.fn().mockResolvedValue('id-token') };

describe('useSessionRefresh (KAN-183)', () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.signOut.mockResolvedValue(undefined);
    Object.defineProperty(window, 'location', { value: { assign }, configurable: true });
  });

  afterEach(() => {
    mocks.idTokenListener = null;
  });

  it('refreshes with the ID token and stays put when the refresh succeeds', async () => {
    mocks.refreshSessionAction.mockResolvedValue({ success: true, data: {} });
    renderHook(() => useSessionRefresh());

    await mocks.idTokenListener?.(USER);

    expect(mocks.refreshSessionAction).toHaveBeenCalledWith('id-token');
    expect(mocks.signOut).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it('signs out and goes to /login when the API rejected the refresh', async () => {
    mocks.refreshSessionAction.mockResolvedValue({
      success: false,
      error: 'Token verification failed',
      data: { signInRequired: true },
    });
    renderHook(() => useSessionRefresh());

    await mocks.idTokenListener?.(USER);

    await waitFor(() => expect(assign).toHaveBeenCalledWith('/login'));
    expect(mocks.signOut).toHaveBeenCalledTimes(1);
  });

  it('keeps the session on a transient failure (no sign-in demanded)', async () => {
    mocks.refreshSessionAction.mockResolvedValue({
      success: false,
      error: 'Token verification failed',
    });
    renderHook(() => useSessionRefresh());

    await mocks.idTokenListener?.(USER);

    expect(mocks.signOut).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });
});
