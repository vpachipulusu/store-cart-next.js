// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Prisma } from '@prisma/client';
import type Stripe from 'stripe';

const { create, findUnique, update, updateMany, deleteMany, handleWebhookEvent } = vi.hoisted(
  () => ({
    create: vi.fn(),
    findUnique: vi.fn(),
    update: vi.fn(),
    updateMany: vi.fn(),
    deleteMany: vi.fn(),
    handleWebhookEvent: vi.fn(),
  })
);
vi.mock('@/lib/db/client', () => ({
  db: { processedStripeEvent: { create, findUnique, update, updateMany, deleteMany } },
}));
vi.mock('@/lib/stripe/webhooks', () => ({ handleWebhookEvent }));

vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import {
  processWebhookEvent,
  WebhookInProgressError,
  WEBHOOK_LEASE_MS,
} from '@/lib/stripe/webhook-processing';

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
    updateMany.mockResolvedValue({ count: 1 });
    deleteMany.mockResolvedValue({ count: 1 });
    handleWebhookEvent.mockResolvedValue(undefined);
  });

  it('records, handles and marks a new event processed', async () => {
    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('processed');
    expect(create).toHaveBeenCalledWith({
      data: { id: 'evt_1', type: EVENT.type, claimedAt: expect.any(Date) },
    });
    expect(handleWebhookEvent).toHaveBeenCalledWith(EVENT);
    expect(update).toHaveBeenCalledWith({
      where: { id: 'evt_1' },
      data: { processedAt: expect.any(Date) },
    });
  });

  it('skips an event that was already processed', async () => {
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({
      id: 'evt_1',
      processedAt: new Date(),
      claimedAt: new Date(),
    });

    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('duplicate');
    expect(handleWebhookEvent).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });

  it('fails without running the handler while another delivery holds a live lease', async () => {
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({ id: 'evt_1', processedAt: null, claimedAt: new Date() });

    await expect(processWebhookEvent(EVENT)).rejects.toBeInstanceOf(WebhookInProgressError);
    expect(handleWebhookEvent).not.toHaveBeenCalled();
    expect(updateMany).not.toHaveBeenCalled();
  });

  it('takes over an expired lease and runs the handler once', async () => {
    const claimedAt = new Date(Date.now() - WEBHOOK_LEASE_MS - 1000);
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({ id: 'evt_1', processedAt: null, claimedAt });

    const result = await processWebhookEvent(EVENT);

    expect(result).toBe('processed');
    expect(updateMany).toHaveBeenCalledWith({
      where: { id: 'evt_1', processedAt: null, claimedAt },
      data: { claimedAt: expect.any(Date) },
    });
    expect(handleWebhookEvent).toHaveBeenCalledTimes(1);
  });

  it('does not run the handler when losing the takeover race', async () => {
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({
      id: 'evt_1',
      processedAt: null,
      claimedAt: new Date(Date.now() - WEBHOOK_LEASE_MS - 1000),
    });
    updateMany.mockResolvedValue({ count: 0 });

    await expect(processWebhookEvent(EVENT)).rejects.toBeInstanceOf(WebhookInProgressError);
    expect(handleWebhookEvent).not.toHaveBeenCalled();
  });

  it('releases the claim and does not mark processed when the handler throws', async () => {
    handleWebhookEvent.mockRejectedValue(new Error('boom'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('boom');
    expect(update).not.toHaveBeenCalled();
    expect(deleteMany).toHaveBeenCalledWith({
      where: { id: 'evt_1', processedAt: null, claimedAt: create.mock.calls[0][0].data.claimedAt },
    });
  });

  it('releases only its own claim, scoped by the claimedAt it holds', async () => {
    const claimedAt = new Date(Date.now() - WEBHOOK_LEASE_MS - 1000);
    create.mockRejectedValue(uniqueViolation());
    findUnique.mockResolvedValue({ id: 'evt_1', processedAt: null, claimedAt });
    handleWebhookEvent.mockRejectedValue(new Error('boom'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('boom');

    const takeoverClaim = updateMany.mock.calls[0][0].data.claimedAt;
    expect(takeoverClaim.getTime()).not.toBe(claimedAt.getTime());
    expect(deleteMany).toHaveBeenCalledWith({
      where: { id: 'evt_1', processedAt: null, claimedAt: takeoverClaim },
    });
  });

  it('still rethrows the handler error when releasing the claim fails', async () => {
    handleWebhookEvent.mockRejectedValue(new Error('boom'));
    deleteMany.mockRejectedValue(new Error('db down'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('boom');
  });

  it('propagates non-unique database errors without handling the event', async () => {
    create.mockRejectedValue(new Error('connection lost'));

    await expect(processWebhookEvent(EVENT)).rejects.toThrow('connection lost');
    expect(handleWebhookEvent).not.toHaveBeenCalled();
  });
});
