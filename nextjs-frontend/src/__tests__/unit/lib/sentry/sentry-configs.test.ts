/** KAN-62: every Sentry config wires the invitation token scrubber into its three hooks. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ init: vi.fn() }));

vi.mock('@sentry/nextjs', () => ({
  init: mocks.init,
  captureRouterTransitionStart: vi.fn(),
}));

describe.each([
  ['server', () => import('../../../../../sentry.server.config')],
  ['edge', () => import('../../../../../sentry.edge.config')],
  ['client', () => import('@/instrumentation-client')],
])('%s Sentry config', (_name, load) => {
  beforeEach(() => {
    vi.resetModules();
    mocks.init.mockClear();
  });

  it('passes the scrubbing hooks to Sentry.init', async () => {
    await load();
    // Same module registry as the config just loaded (resetModules gives each case a fresh one).
    const { INVITE_TOKEN_SENTRY_HOOKS } = await import('@/lib/sentry/scrub-invite-token');

    expect(mocks.init).toHaveBeenCalledTimes(1);
    expect(mocks.init.mock.calls[0][0]).toMatchObject(INVITE_TOKEN_SENTRY_HOOKS);
  });
});
