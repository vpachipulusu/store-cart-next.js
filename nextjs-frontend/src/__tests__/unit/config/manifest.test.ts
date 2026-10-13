import { afterEach, describe, expect, it, vi } from 'vitest';

describe('app/manifest', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('builds the web manifest from siteConfig', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_NAME', 'Acme Shop');
    vi.resetModules();
    const { default: manifest } = await import('@/app/manifest');
    const result = manifest();
    expect(result.name).toBe('Acme Shop');
    expect(result.short_name).toBe('Acme Shop');
    expect(result.description).toBeTruthy();
    expect(result.start_url).toBe('/');
    expect(result.display).toBe('standalone');
    expect(result.icons?.length).toBeGreaterThan(0);
  });
});
