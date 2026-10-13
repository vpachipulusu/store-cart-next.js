import { NextResponse } from 'next/server';
import { logger } from '@/lib/logger';

export const dynamic = 'force-dynamic';

const BACKEND_TIMEOUT_MS = 3000;
const NO_STORE = { 'Cache-Control': 'no-store' };

function unhealthy() {
  return NextResponse.json({ status: 'unavailable' }, { status: 503, headers: NO_STORE });
}

/**
 * Deployment health (KAN-112). Public and unauthenticated. The FastAPI backend is an
 * internal service, so this route reaches it server-side through BACKEND_API_URL.
 * Failure detail is logged here and never returned to the caller.
 */
export async function GET() {
  const backendUrl = process.env.BACKEND_API_URL;
  if (!backendUrl) {
    logger.error('Health check failed: BACKEND_API_URL is not set');
    return unhealthy();
  }

  try {
    const response = await fetch(`${backendUrl.replace(/\/+$/, '')}/health`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    if (!response.ok) {
      logger.error('Health check failed: backend returned a non-200 status', {
        status: response.status,
      });
      return unhealthy();
    }
    return NextResponse.json({ status: 'ok' }, { headers: NO_STORE });
  } catch (error) {
    logger.error('Health check failed: backend unreachable', { error });
    return unhealthy();
  }
}
