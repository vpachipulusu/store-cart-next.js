import { vi } from 'vitest';

/** Mirrors the digest shape of Next.js redirect errors so unstable_rethrow behaves like production. */
export function makeRedirectError(url: string): Error & { digest: string } {
  return Object.assign(new Error('NEXT_REDIRECT'), {
    digest: `NEXT_REDIRECT;replace;${url};307;`,
  });
}

export function redirectTarget(error: unknown): string | null {
  const digest = (error as { digest?: unknown } | null)?.digest;
  return typeof digest === 'string' && digest.startsWith('NEXT_REDIRECT;')
    ? digest.split(';')[2]
    : null;
}

export const navigationMock = {
  redirect: vi.fn((url: string) => {
    throw makeRedirectError(url);
  }),
  unstable_rethrow: vi.fn((error: unknown) => {
    if (redirectTarget(error) !== null) throw error;
  }),
};

export const SESSION_EXPIRED = Object.assign(new Error('expired'), {
  code: 'auth/session-cookie-expired',
});
/** What `fetchSessionStatus` returns for a revoked, expired or invalid session cookie (KAN-208). */
export const REVOKED_SESSION = { success: false, error: 'Invalid authentication', status: 401 };
/** What `fetchSessionStatus` returns when the backend is down: the user must stay signed in. */
export const SESSION_CHECK_DOWN = { success: false, error: 'Backend unavailable' };
export const DB_DOWN = Object.assign(new Error('connection refused'), { code: 'P1001' });

export async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected promise to reject');
}
