import { describe, expect, it } from 'vitest';
import {
  isStalledProvisioning,
  isStoreInSetup,
  STUCK_AFTER_MINUTES,
} from '@/lib/stores/provisioning';

const NOW = Date.parse('2026-10-19T12:00:00Z');
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

describe('isStalledProvisioning', () => {
  it('mirrors the backend 15-minute threshold', () => {
    expect(STUCK_AFTER_MINUTES).toBe(15);
  });

  it('is true for a PROVISIONING store unchanged for longer than the threshold', () => {
    expect(isStalledProvisioning('PROVISIONING', minutesAgo(16), NOW)).toBe(true);
    expect(isStalledProvisioning('PROVISIONING', minutesAgo(60 * 24), NOW)).toBe(true);
  });

  it('is false at or inside the threshold, where the job may still be running', () => {
    expect(isStalledProvisioning('PROVISIONING', minutesAgo(15), NOW)).toBe(false);
    expect(isStalledProvisioning('PROVISIONING', minutesAgo(1), NOW)).toBe(false);
  });

  it.each(['ACTIVE', 'FAILED', 'SUSPENDED', 'ARCHIVED'])('is false for a %s store', (status) => {
    expect(isStalledProvisioning(status, minutesAgo(60), NOW)).toBe(false);
  });

  it('is false for a malformed date instead of offering a re-run', () => {
    expect(isStalledProvisioning('PROVISIONING', 'not a date', NOW)).toBe(false);
  });
});

describe('isStoreInSetup', () => {
  it.each(['PROVISIONING', 'FAILED'])('is true for %s', (status) => {
    expect(isStoreInSetup(status)).toBe(true);
  });

  it.each(['ACTIVE', 'SUSPENDED', 'ARCHIVED', ''])('is false for "%s"', (status) => {
    expect(isStoreInSetup(status)).toBe(false);
  });
});
