import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '@/proxy';

const call = (path: string, cookie?: string) =>
  proxy(new NextRequest(`http://localhost${path}`, cookie ? { headers: { cookie } } : undefined));

/**
 * KAN-123: the proxy runs at the edge and cannot verify Firebase claims, so the client-writable
 * `email-verified` cookie must have no influence on its decisions. The signed claim is enforced by
 * the server boundary (see unit/auth/verified-session.test.ts and the layout tests).
 */
describe('proxy ignores the email-verified cookie', () => {
  it.each(['/dashboard', '/dashboard/profile', '/settings', '/profile', '/security'])(
    '%s behaves identically for email-verified=false, true and absent',
    async (path) => {
      const absent = await call(path, 'session=abc');
      const forgedFalse = await call(path, 'session=abc; email-verified=false');
      const forgedTrue = await call(path, 'session=abc; email-verified=true');

      for (const response of [absent, forgedFalse, forgedTrue]) {
        expect(response.status).toBe(200);
        expect(response.headers.get('location')).toBeNull();
      }
    }
  );

  it('does not redirect to /verify-email on email-verified=false', async () => {
    const response = await call('/dashboard', 'session=abc; email-verified=false');

    expect(response.headers.get('location') ?? '').not.toContain('/verify-email');
  });

  it('still redirects to /login when there is no session, whatever the cookie says', async () => {
    const response = await call('/dashboard', 'email-verified=true');

    expect(response.status).toBe(307);
    expect(new URL(response.headers.get('location')!).pathname).toBe('/login');
  });
});
