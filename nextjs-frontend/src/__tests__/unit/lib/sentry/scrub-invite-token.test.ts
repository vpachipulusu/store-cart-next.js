import { describe, expect, it } from 'vitest';
import {
  INVITE_TOKEN_SENTRY_HOOKS,
  scrubBreadcrumb,
  scrubInviteTokenText,
  scrubInviteTokens,
  scrubSentryEvent,
} from '@/lib/sentry/scrub-invite-token';

const TOKEN = 'AbC_def-1234567890ghijklmnopqrstuvwxyz0123';

describe('scrubInviteTokenText', () => {
  it.each([
    [`/invite/${TOKEN}`, '/invite/[token]'],
    [
      `https://app.example.com/invite/${TOKEN}?x=1#y`,
      'https://app.example.com/invite/[token]?x=1#y',
    ],
    [`GET /invite/${TOKEN} 200`, 'GET /invite/[token] 200'],
    [`%2Finvite%2F${TOKEN}%2Fnext`, '%2Finvite%2F[token]%2Fnext'],
    [`%2finvite%2f${TOKEN}`, '%2finvite%2f[token]'],
    [`/INVITE/${TOKEN}`, '/INVITE/[token]'],
    ['/invite/[token]', '/invite/[token]'],
    ['/dashboard/settings/team', '/dashboard/settings/team'],
  ])('scrubs %s', (input, expected) => {
    expect(scrubInviteTokenText(input)).toBe(expected);
  });
});

describe('scrubInviteTokens', () => {
  it('returns a scrubbed copy and leaves the input unchanged', () => {
    const event = {
      transaction: `/invite/${TOKEN}`,
      request: { url: `https://app.example.com/invite/${TOKEN}` },
      breadcrumbs: [{ data: { from: `/invite/${TOKEN}`, to: '/dashboard' } }],
      extra: { count: 3, ok: true, nothing: null },
    };
    const before = JSON.stringify(event);

    const result = scrubInviteTokens(event);

    expect(result).not.toBe(event);
    expect(JSON.stringify(result)).not.toContain(TOKEN);
    expect(result.breadcrumbs[0].data.to).toBe('/dashboard');
    expect(result.extra).toEqual({ count: 3, ok: true, nothing: null });
    expect(JSON.stringify(event)).toBe(before);
  });

  it('handles frozen input without throwing', () => {
    const frozen = Object.freeze({
      url: `/invite/${TOKEN}`,
      nested: Object.freeze({ to: `/invite/${TOKEN}` }),
    });

    const result = scrubInviteTokens(frozen);

    expect(result).toEqual({ url: '/invite/[token]', nested: { to: '/invite/[token]' } });
    expect(frozen.url).toBe(`/invite/${TOKEN}`);
  });

  it('marks cycles instead of looping', () => {
    const cyclic: Record<string, unknown> = { url: `/invite/${TOKEN}` };
    cyclic.self = cyclic;

    const result = scrubInviteTokens(cyclic) as Record<string, unknown>;

    expect(result.url).toBe('/invite/[token]');
    expect(result.self).toBe('[Circular]');
    expect(cyclic.self).toBe(cyclic);
  });

  it('leaves class instances and live objects alone (never descends into them)', () => {
    class Live {
      href = `/invite/${TOKEN}`;
    }
    const live = new Live();
    const map = new Map([['k', `/invite/${TOKEN}`]]);

    const result = scrubInviteTokens({ live, map });

    expect(result.live).toBe(live);
    expect(live.href).toBe(`/invite/${TOKEN}`);
    expect(result.map).toBe(map);
  });

  it('caps the depth', () => {
    let deep: Record<string, unknown> = { url: `/invite/${TOKEN}` };
    for (let level = 0; level < 20; level += 1) deep = { next: deep };

    expect(JSON.stringify(scrubInviteTokens(deep))).toContain('[Truncated]');
  });
});

describe('scrubSentryEvent', () => {
  it('drops the Next.js router headers and scrubs the rest', () => {
    const event = {
      request: {
        url: `https://app.example.com/invite/${TOKEN}`,
        headers: {
          'Next-Router-State-Tree': encodeURIComponent(
            JSON.stringify(['', { children: ['invite', ['token', TOKEN, 'd']] }])
          ),
          'next-url': `/invite/${TOKEN}`,
          'next-router-segment-prefetch': `/invite/${TOKEN}`,
          referer: `https://app.example.com/invite/${TOKEN}`,
          'user-agent': 'test',
        },
      },
    };

    const result = scrubSentryEvent(event)!;

    expect(Object.keys(result.request.headers)).toEqual(['referer', 'user-agent']);
    expect(JSON.stringify(result)).not.toContain(TOKEN);
    expect(event.request.headers['next-url']).toBe(`/invite/${TOKEN}`);
  });

  it('keeps events without request headers', () => {
    expect(scrubSentryEvent({ message: `see /invite/${TOKEN}` })).toEqual({
      message: 'see /invite/[token]',
    });
  });

  it('fails closed when scrubbing throws', () => {
    const hostile = {};
    Object.defineProperty(hostile, 'boom', {
      enumerable: true,
      get() {
        throw new Error('getter');
      },
    });

    expect(scrubSentryEvent(hostile)).toBeNull();
  });
});

describe('scrubBreadcrumb', () => {
  it('drops the logged arguments of console breadcrumbs and scrubs the message', () => {
    const logged = { location: `/invite/${TOKEN}` };
    const breadcrumb = {
      category: 'console',
      message: `visited /invite/${TOKEN}`,
      data: { arguments: [logged], logger: 'console' },
    };

    const result = scrubBreadcrumb(breadcrumb)!;

    expect(result).toEqual({
      category: 'console',
      message: 'visited /invite/[token]',
      data: { logger: 'console' },
    });
    expect(breadcrumb.data.arguments[0]).toBe(logged);
  });

  it('scrubs navigation breadcrumbs', () => {
    expect(
      scrubBreadcrumb({
        category: 'navigation',
        data: { from: `/invite/${TOKEN}`, to: '/dashboard' },
      })
    ).toEqual({ category: 'navigation', data: { from: '/invite/[token]', to: '/dashboard' } });
  });

  it('fails closed when scrubbing throws', () => {
    const data = {};
    Object.defineProperty(data, 'boom', {
      enumerable: true,
      get() {
        throw new Error('getter');
      },
    });

    expect(scrubBreadcrumb({ category: 'xhr', data })).toBeNull();
  });
});

it('exposes the three hooks', () => {
  expect(INVITE_TOKEN_SENTRY_HOOKS).toEqual({
    beforeSend: scrubSentryEvent,
    beforeSendTransaction: scrubSentryEvent,
    beforeBreadcrumb: scrubBreadcrumb,
  });
});
