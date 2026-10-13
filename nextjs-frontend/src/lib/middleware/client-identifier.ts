import { isIP } from 'node:net';
import type { NextRequest } from 'next/server';

function validIp(value: string | null): string | null {
  const ip = value?.trim();
  return ip && isIP(ip) !== 0 ? ip : null;
}

/** Select an identity only across a trusted platform boundary, never from raw forwarded headers. */
export function getClientIdentifier(request: NextRequest): string {
  if (process.env.VERCEL === '1') {
    // Vercel supplies this header independently of caller-supplied X-Forwarded-For.
    // https://vercel.com/docs/headers/request-headers#x-vercel-forwarded-for
    return validIp(request.headers.get('x-vercel-forwarded-for')) ?? 'unknown';
  }

  // next.config.ts bakes this flag off in ordinary builds. The runtime restrictions also
  // reject an E2E artifact deployed to Vercel, including preview and development deployments.
  const localE2e =
    process.env.E2E_RATE_LIMIT_TEST_MODE === '1' &&
    ['.next-e2e', '.next-e2e-dev'].includes(process.env.NEXT_DIST_DIR ?? '') &&
    !process.env.VERCEL &&
    !process.env.VERCEL_ENV &&
    ['localhost', '127.0.0.1', '[::1]'].includes(request.nextUrl.hostname);
  if (localE2e) {
    const testIp = validIp(request.headers.get('x-e2e-client-ip'));
    if (testIp) return `e2e:${testIp}`;
  }

  // Outside Vercel there is no established trusted proxy; share a conservative bucket.
  return 'unknown';
}
