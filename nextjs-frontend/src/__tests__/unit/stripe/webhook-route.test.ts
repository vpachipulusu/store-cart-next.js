// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const headerGet = vi.fn();
vi.mock('next/headers', () => ({
  headers: vi.fn(async () => ({ get: headerGet })),
}));

const verifyWebhookSignature = vi.fn();
vi.mock('@/lib/stripe/webhooks', () => ({
  verifyWebhookSignature: (...args: unknown[]) => verifyWebhookSignature(...args),
}));

const processWebhookEvent = vi.fn();
vi.mock('@/lib/stripe/webhook-processing', () => ({
  processWebhookEvent: (...args: unknown[]) => processWebhookEvent(...args),
}));

vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { POST } from '@/app/api/webhooks/stripe/route';
import { logger } from '@/lib/logger';

const EVENT = { id: 'evt_1', type: 'invoice.payment_succeeded' };

function makeRequest(): NextRequest {
  return new NextRequest('http://localhost/api/webhooks/stripe', {
    method: 'POST',
    body: JSON.stringify(EVENT),
  });
}

describe('POST /api/webhooks/stripe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    headerGet.mockReturnValue('t=1,v1=sig');
    verifyWebhookSignature.mockReturnValue(EVENT);
    processWebhookEvent.mockResolvedValue('processed');
  });

  it('returns 200 when the event is processed', async () => {
    const response = await POST(makeRequest());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      received: true,
      eventId: 'evt_1',
      eventType: 'invoice.payment_succeeded',
    });
    expect(processWebhookEvent).toHaveBeenCalledWith(EVENT);
  });

  it('returns 200 and flags a duplicate event that was already processed', async () => {
    processWebhookEvent.mockResolvedValue('duplicate');

    const response = await POST(makeRequest());

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ received: true, duplicate: true });
  });

  it('returns a generic 500 and logs the error when handling fails', async () => {
    processWebhookEvent.mockRejectedValue(new Error('db password leaked'));

    const response = await POST(makeRequest());
    const text = await response.text();

    expect(response.status).toBe(500);
    expect(JSON.parse(text)).toEqual({ error: 'Webhook processing failed' });
    expect(text).not.toContain('leaked');
    expect(logger.error).toHaveBeenCalled();
  });

  it('rejects a bad signature without processing the event', async () => {
    verifyWebhookSignature.mockImplementation(() => {
      throw new Error('No signatures found matching');
    });

    const response = await POST(makeRequest());

    expect(response.status).toBe(401);
    expect(processWebhookEvent).not.toHaveBeenCalled();
  });

  it('rejects a missing signature header with 400', async () => {
    headerGet.mockReturnValue(null);

    const response = await POST(makeRequest());

    expect(response.status).toBe(400);
    expect(verifyWebhookSignature).not.toHaveBeenCalled();
    expect(processWebhookEvent).not.toHaveBeenCalled();
  });

  it('does not export a wildcard-CORS OPTIONS handler (KAN-129)', async () => {
    const route = await import('@/app/api/webhooks/stripe/route');

    expect(route).not.toHaveProperty('OPTIONS');
  });
});
