import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/logger', () => ({
  logger: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

import { GET } from '@/app/api/health/route';
import { logger } from '@/lib/logger';

describe('GET /api/health', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('BACKEND_API_URL', 'https://backend.internal/');
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('returns 200 ok when the backend health check passes', async () => {
    fetchMock.mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));

    const response = await GET();

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://backend.internal/health');
    expect(init.cache).toBe('no-store');
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('returns a generic 503 when the backend is not healthy', async () => {
    fetchMock.mockResolvedValue(new Response('db password leaked', { status: 500 }));

    const response = await GET();

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ status: 'unavailable' });
    expect(logger.error).toHaveBeenCalled();
  });

  it('returns a generic 503 without leaking the error when fetch fails', async () => {
    fetchMock.mockRejectedValue(new Error('connect ECONNREFUSED 10.0.0.1:8000'));

    const response = await GET();

    expect(response.status).toBe(503);
    expect(JSON.stringify(await response.json())).not.toContain('ECONNREFUSED');
    expect(logger.error).toHaveBeenCalled();
  });

  it('returns 503 without calling fetch when BACKEND_API_URL is missing', async () => {
    vi.stubEnv('BACKEND_API_URL', '');

    const response = await GET();

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(logger.error).toHaveBeenCalled();
  });
});
