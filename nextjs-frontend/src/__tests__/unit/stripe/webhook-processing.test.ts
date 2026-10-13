// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Prisma } from '@prisma/client';
import type Stripe from 'stripe';

const { create, findUnique, update, handleWebhookEvent } = vi.hoisted(() => ({
  create: vi.fn(),
  findUnique: vi.fn(),
  update: vi.fn(),
  handleWebhookEvent: vi.fn(),
}));
vi.mock('@/lib/db/client', () => ({
  db: { processedStripeEvent: { create, findUnique, update } },
}));
vi.mock('@/lib/stripe/webhooks', () => ({ handleWebhookEvent }));

vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { processWebhookEvent } from '@/lib/stripe/webhook-processing';

const EVENT = { id: 'evt_1', type: 'invoice.payment_succeeded' } as Stripe.Event;

function uniqueViolation(): Prisma.PrismaClientKnownRequestError {
  return new Prisma.PrismaClientKnownRequestError('Unique constraint failed', {
    code: 'P2002',
    clientVersion: 'test',
  });
}

describe('processWebhookEvent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    create.mockResolvedValue({});
    update.mockResolvedValue({});
    handleWebhookEvent.mockResolvedValue(undefined);
  });

  it('records, handles and marks a new event processed', async () => {
    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('processed');
    expect(create).toHaveBeenCalledWith({ data: { id: 'evt_1', type: EVENT.type } });
    expect(handleWebhookEvent).toHaveBeenCalledWith(EVENT);
    expect(update).toHaveBeenCalledWith({
      where: { id: 'evt_1' },
      data: { processedAt: expect.any(Date) },
    });
  });

  it('skips an event that was already processed', async () => {
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({ id: 'evt_1', processedAt: new Date() });

    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('duplicate');
    expect(handleWebhookEvent).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });

  it('reprocesses an event whose earlier attempt failed', async () => {
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({ id: 'evt_1', processedAt: null });

    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('processed');
    expect(handleWebhookEvent).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('does not mark the event processed when the handler throws', async () => {
    handleWebhookEvent.mockRejectedValue(new Error('boom'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('boom');
    expect(update).not.toHaveBeenCalled();
  });

  it('propagates non-unique database errors without handling the event', async () => {
    create.mockRejectedValue(new Error('connection lost'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('connection lost');
    expect(handleWebhookEvent).not.toHaveBeenCalled();
  });
});
