// @vitest-environment node
/**
 * KAN-126: profile actions must never return secret or internal user columns. The db is mocked to
 * behave like Prisma: it applies the caller's `select`, so a missing `select` returns the full row.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const FULL_ROW: Record<string, unknown> = {
  id: 'user-1',
  firebaseUid: 'fb-uid-secret',
  email: 'a@b.test',
  emailVerified: true,
  createdAt: new Date('2026-01-01T00:00:00Z'),
  updatedAt: new Date('2026-01-02T00:00:00Z'),
  lastLoginAt: new Date('2026-01-03T00:00:00Z'),
  displayName: 'Ada',
  bio: 'bio',
  avatarUrl: null,
  location: 'London',
  website: null,
  phoneNumber: null,
  twoFactorEnabled: true,
  twoFactorSecret: 'JBSWY3DPEHPK3PXP',
  stripeCustomerId: 'cus_123',
  stripeSubscriptionId: 'sub_123',
  stripePriceId: 'price_123',
  stripeCurrentPeriodEnd: new Date('2027-01-01T00:00:00Z'),
  subscriptionTier: 'pro',
  subscriptionStatus: 'active',
  settings: { theme: 'dark' },
};

const ALLOWED_KEYS = [
  'avatarUrl',
  'bio',
  'createdAt',
  'displayName',
  'email',
  'emailVerified',
  'id',
  'location',
  'phoneNumber',
  'subscriptionStatus',
  'subscriptionTier',
  'website',
];

const FORBIDDEN_KEYS = [
  'twoFactorSecret',
  'twoFactorEnabled',
  'firebaseUid',
  'stripeCustomerId',
  'stripeSubscriptionId',
  'stripePriceId',
  'stripeCurrentPeriodEnd',
  'updatedAt',
  'lastLoginAt',
];

function applySelect(row: Record<string, unknown>, select?: Record<string, boolean>) {
  if (!select) return { ...row };
  return Object.fromEntries(Object.keys(select).map((key) => [key, row[key]]));
}

const mocks = vi.hoisted(() => ({
  getVerifiedUserId: vi.fn(),
  findUnique: vi.fn(),
  update: vi.fn(),
}));

vi.mock('next/headers', () => ({ cookies: vi.fn(), headers: vi.fn() }));
vi.mock('@/lib/firebase/admin', () => ({ getAdminAuth: vi.fn() }));
vi.mock('@/lib/auth/verified-session', () => ({ getVerifiedUserId: mocks.getVerifiedUserId }));
vi.mock('@/lib/db/client', () => ({
  db: { user: { findUnique: mocks.findUnique, update: mocks.update } },
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/stripe/subscriptions', () => ({ cancelSubscription: vi.fn() }));
vi.mock('@/lib/utils/notifications', () => ({ notifyPasswordChanged: vi.fn() }));

import { getUserProfileAction, updateUserProfileAction } from '@/app/actions/user-actions';

describe('KAN-126: profile actions return only safe fields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getVerifiedUserId.mockResolvedValue('user-1');
    mocks.findUnique.mockImplementation(async ({ select }) => applySelect(FULL_ROW, select));
    mocks.update.mockImplementation(async ({ select }) => applySelect(FULL_ROW, select));
  });

  it('updateUserProfileAction returns no secret fields and only allowed keys', async () => {
    const result = await updateUserProfileAction({ displayName: 'Ada' });

    expect(result.success).toBe(true);
    const user = result.data.user;
    expect(user).not.toHaveProperty('twoFactorSecret');
    for (const key of FORBIDDEN_KEYS) expect(user).not.toHaveProperty(key);
    expect(Object.keys(user).sort()).toEqual(ALLOWED_KEYS);
    expect(JSON.stringify(result)).not.toContain('JBSWY3DPEHPK3PXP');
  });

  it('updateUserProfileAction passes an explicit select to the update', async () => {
    await updateUserProfileAction({ displayName: 'Ada' });

    expect(mocks.update.mock.calls[0][0].select).toBeDefined();
  });

  it('getUserProfileAction returns no secret fields and only allowed keys plus settings', async () => {
    const result = await getUserProfileAction();

    expect(result.success).toBe(true);
    const user = result.data.user;
    expect(user).not.toHaveProperty('twoFactorSecret');
    for (const key of FORBIDDEN_KEYS) expect(user).not.toHaveProperty(key);
    expect(Object.keys(user).sort()).toEqual([...ALLOWED_KEYS, 'settings'].sort());
    expect(user.settings).toEqual({ theme: 'dark' });
  });

  it('returns Unauthorized without touching the db when there is no verified user', async () => {
    mocks.getVerifiedUserId.mockResolvedValue(null);

    expect(await updateUserProfileAction({ displayName: 'x' })).toMatchObject({
      success: false,
      error: 'Unauthorized',
    });
    expect(mocks.update).not.toHaveBeenCalled();
  });
});
