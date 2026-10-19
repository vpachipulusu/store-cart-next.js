// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { getClientIdentifier } from '@/lib/middleware/client-identifier';

function request(headers: Record<string, string> = {}, host = 'localhost') {
  return new NextRequest(`http://${host}/api/auth/login`, { headers });
}

describe('rate-limit client identity', () => {
  beforeEach(() => {
    vi.stubEnv('VERCEL', '');
    vi.stubEnv('VERCEL_ENV', '');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '0');
    vi.stubEnv('NEXT_DIST_DIR', '.next');
  });
  afterEach(() => vi.unstubAllEnvs());

  it('ignores all forwarded headers outside Vercel', () => {
    expect(
      getClientIdentifier(
        request({
          'x-forwarded-for': '192.0.2.1',
          'x-real-ip': '192.0.2.2',
          'x-vercel-forwarded-for': '192.0.2.3',
        })
      )
    ).toBe('unknown');
  });

  it.each(['192.0.2.1', '2001:db8::1'])('uses the trusted Vercel IP %s', (ip) => {
    vi.stubEnv('VERCEL', '1');
    expect(
      getClientIdentifier(
        request({
          'x-vercel-forwarded-for': ip,
          'x-forwarded-for': '192.0.2.99',
        })
      )
    ).toBe(ip);
  });

  it.each(['', 'invalid', '192.0.2.1, 192.0.2.2', '999.0.0.1'])(
    'fails closed for malformed trusted input %s',
    (ip) => {
      vi.stubEnv('VERCEL', '1');
      expect(getClientIdentifier(request({ 'x-vercel-forwarded-for': ip }))).toBe('unknown');
    }
  );

  it('does not fall back to spoofable headers when the trusted header is missing', () => {
    vi.stubEnv('VERCEL', '1');
    expect(getClientIdentifier(request({ 'x-forwarded-for': '192.0.2.1' }))).toBe('unknown');
  });

  it('supports isolated identities in a dedicated local production-style E2E build', () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }))).toBe('e2e:10.1.2.3');
  });

  it.each(['production', 'preview', 'development'])(
    'rejects E2E overrides on Vercel %s',
    (environment) => {
      vi.stubEnv('VERCEL', '1');
      vi.stubEnv('VERCEL_ENV', environment);
      vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
      vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
      expect(
        getClientIdentifier(
          request({
            'x-e2e-client-ip': '10.1.2.3',
            'x-vercel-forwarded-for': '192.0.2.1',
          })
        )
      ).toBe('192.0.2.1');
    }
  );

  it('rejects an override on an ordinary build even with the switch set', () => {
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }))).toBe('unknown');
  });

  it('rejects an override without explicit opt-in', () => {
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }))).toBe('unknown');
  });

  it('rejects an override when only the deployment environment marker is present', () => {
    vi.stubEnv('VERCEL_ENV', 'production');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }))).toBe('unknown');
  });

  it('supports the dedicated E2E dev server', () => {
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e-dev');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }))).toBe('e2e:10.1.2.3');
  });

  it('rejects an override for a non-loopback request', () => {
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': '10.1.2.3' }, 'example.com'))).toBe(
      'unknown'
    );
  });

  it('rejects malformed test identities', () => {
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    expect(getClientIdentifier(request({ 'x-e2e-client-ip': 'anything' }))).toBe('unknown');
  });
});

describe('proxy rate-limit enforcement', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VERCEL', '');
    vi.stubEnv('VERCEL_ENV', '');
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '0');
    vi.stubEnv('NEXT_DIST_DIR', '.next');
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it('rotating forged IP headers cannot reset the authentication bucket', async () => {
    const { proxy } = await import('@/proxy');
    for (let index = 1; index <= 5; index += 1) {
      const response = await proxy(
        request({
          'x-forwarded-for': `192.0.2.${index}`,
          'x-real-ip': `198.51.100.${index}`,
          'x-vercel-forwarded-for': `203.0.113.${index}`,
          'x-e2e-client-ip': `10.1.1.${index}`,
        })
      );
      expect(response.status).toBe(401);
    }
    const response = await proxy(request({ 'x-forwarded-for': '192.0.2.99' }));
    expect(response.status).toBe(429);
    expect(response.headers.get('X-RateLimit-Remaining')).toBe('0');
  });

  it('keeps separate auth buckets for explicit local E2E identities', async () => {
    vi.stubEnv('E2E_RATE_LIMIT_TEST_MODE', '1');
    vi.stubEnv('NEXT_DIST_DIR', '.next-e2e');
    const { proxy } = await import('@/proxy');
    for (let index = 0; index < 5; index += 1) {
      expect((await proxy(request({ 'x-e2e-client-ip': '10.1.1.1' }))).status).toBe(401);
    }
    expect((await proxy(request({ 'x-e2e-client-ip': '10.1.1.1' }))).status).toBe(429);
    expect((await proxy(request({ 'x-e2e-client-ip': '10.1.1.2' }))).status).toBe(401);
  });

  it('limits store-host requests per trusted visitor, not across visitors (KAN-75)', async () => {
    vi.stubEnv('VERCEL', '1');
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.test');
    const { proxy } = await import('@/proxy');
    const { NextRequest } = await import('next/server');
    const visit = (ip: string) =>
      proxy(
        new NextRequest('https://acme.storecart.test/products/x', {
          headers: { host: 'acme.storecart.test', 'x-vercel-forwarded-for': ip },
        })
      );
    for (let index = 0; index < 300; index += 1) {
      expect((await visit('203.0.113.7')).status).not.toBe(429);
    }
    const limited = await visit('203.0.113.7');
    expect(limited.status).toBe(429);
    expect(limited.headers.get('Retry-After')).toMatch(/^\d+$/);
    expect((await visit('203.0.113.8')).status).not.toBe(429);
  });

  it('does not put every store visitor in one bucket when no trusted IP exists', async () => {
    vi.stubEnv('PLATFORM_ROOT_DOMAIN', 'storecart.test');
    const { proxy } = await import('@/proxy');
    const { NextRequest } = await import('next/server');
    for (let index = 0; index < 305; index += 1) {
      const response = await proxy(
        new NextRequest('http://acme.storecart.test/', { headers: { host: 'acme.storecart.test' } })
      );
      expect(response.status).not.toBe(429);
    }
  });
});
