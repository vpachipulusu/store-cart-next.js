import { afterEach, describe, expect, it, vi } from 'vitest';

async function loadSiteConfig() {
  vi.resetModules();
  const mod = await import('@/config/site');
  return mod.siteConfig;
}

describe('siteConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('takes the name from NEXT_PUBLIC_APP_NAME', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_NAME', 'Acme Shop');
    expect((await loadSiteConfig()).name).toBe('Acme Shop');
  });

  it('falls back to a non-empty default name when the env var is unset', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_NAME', '');
    expect((await loadSiteConfig()).name.length).toBeGreaterThan(0);
  });

  it('takes url and supportEmail from env with safe defaults', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_URL', '');
    vi.stubEnv('NEXT_PUBLIC_SUPPORT_EMAIL', '');
    const defaults = await loadSiteConfig();
    expect(defaults.url).toBe('http://localhost:3000');
    expect(defaults.supportEmail).toContain('@');

    vi.stubEnv('NEXT_PUBLIC_APP_URL', 'https://shop.example.com');
    vi.stubEnv('NEXT_PUBLIC_SUPPORT_EMAIL', 'help@shop.example.com');
    const custom = await loadSiteConfig();
    expect(custom.url).toBe('https://shop.example.com');
    expect(custom.supportEmail).toBe('help@shop.example.com');
  });

  it('has a description', async () => {
    expect((await loadSiteConfig()).description.length).toBeGreaterThan(0);
  });
});
