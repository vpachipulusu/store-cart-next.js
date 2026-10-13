// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@sentry/nextjs', () => ({ withSentryConfig: (config: unknown) => config }));

async function compiledTestFlag() {
  vi.resetModules();
  return (await import('../../../../next.config')).default.env?.E2E_RATE_LIMIT_TEST_MODE;
}

describe('rate-limit test override build guard', () => {
  beforeEach(() => {
    vi.stubEnv('VERCEL', '');
    vi.stubEnv('VERCEL_ENV', '');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next');
  });
  afterEach(() => vi.unstubAllEnvs());

  it('compiles out overrides from ordinary builds even when opted in', async () => {
    expect(await compiledTestFlag()).toBe('0');
  });
  it.each(['.next-e2e', '.next-e2e-dev'])(
    'opts in only for the dedicated local %s build',
    async (distDir) => {
      vi.stubEnv('NEXT_DIST_DIR', distDir);
      expect(await compiledTestFlag()).toBe('1');
    }
  );
  it('requires explicit opt-in even for E2E builds', async () => {
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '0');
    expect(await compiledTestFlag()).toBe('0');
  });
  it.each(['production', 'preview', 'development'])(
    'compiles out overrides on Vercel %s',
    async (environment) => {
      vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
      vi.stubEnv('VERCEL', '1');
      vi.stubEnv('VERCEL_ENV', environment);
      expect(await compiledTestFlag()).toBe('0');
    }
  );
  it('fails closed when only the Vercel environment marker is present', async () => {
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    vi.stubEnv('VERCEL_ENV', 'production');
    expect(await compiledTestFlag()).toBe('0');
  });
});
