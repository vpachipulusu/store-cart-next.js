import { describe, expect, it } from 'vitest';
import { scrubInviteTokenText, scrubInviteTokens } from '@/lib/sentry/scrub-invite-token';

const TOKEN = 'AbC_def-1234567890ghijklmnopqrstuvwxyz0123';

describe('scrubInviteTokens', () => {
  it.each([
    [`/invite/${TOKEN}`, '/invite/[token]'],
    [
      `https://app.example.com/invite/${TOKEN}?x=1#y`,
      'https://app.example.com/invite/[token]?x=1#y',
    ],
    [`GET /invite/${TOKEN} 200`, 'GET /invite/[token] 200'],
    ['/invite/[token]', '/invite/[token]'],
    ['/dashboard/settings/team', '/dashboard/settings/team'],
  ])('scrubs %s', (input, expected) => {
    expect(scrubInviteTokenText(input)).toBe(expected);
  });

  it('scrubs every string in an event, in place', () => {
    const event = {
      transaction: `/invite/${TOKEN}`,
      request: {
        url: `https://app.example.com/invite/${TOKEN}`,
        headers: { Referer: `/invite/${TOKEN}` },
      },
      breadcrumbs: [{ data: { from: `/invite/${TOKEN}`, to: '/dashboard' } }],
      extra: { count: 3, ok: true, nothing: null },
    };

    const result = scrubInviteTokens(event);

    expect(result).toBe(event);
    expect(JSON.stringify(result)).not.toContain(TOKEN);
    expect(result.breadcrumbs[0].data.to).toBe('/dashboard');
    expect(result.extra).toEqual({ count: 3, ok: true, nothing: null });
  });

  it('stops at a bounded depth', () => {
    let deep: Record<string, unknown> = { url: `/invite/${TOKEN}` };
    for (let level = 0; level < 20; level += 1) deep = { next: deep };

    expect(() => scrubInviteTokens(deep)).not.toThrow();
  });
});
