import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '@/proxy';

/** KAN-62: invitation links carry a single-use token in the path, so they never send a referrer. */
describe('proxy referrer policy for invitation links', () => {
  it('sends no referrer from /invite/<token>', async () => {
    const response = await proxy(new NextRequest('http://localhost/invite/AbC_def-1234567890ghij'));

    expect(response.headers.get('Referrer-Policy')).toBe('no-referrer');
  });

  it('keeps the default policy elsewhere', async () => {
    const response = await proxy(new NextRequest('http://localhost/pricing'));

    expect(response.headers.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin');
  });
});
