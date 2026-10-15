// @vitest-environment node
/**
 * KAN-169: admin user and subscription actions must never return secret or internal user columns.
 * The db is mocked to behave like Prisma: it applies the caller's `select` (including nested
 * relation selects), so a missing `select` or `include` returns the full row.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const FULL_USER: Record<string, unknown> = {
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
  settings: { id: 's1', userId: 'user-1', theme: 'dark' },
  adminUser: {
    id: 'a1',
    userId: 'user-1',
    role: 'admin',
    permissions: ['*'],
    createdAt: new Date('2026-01-01T00:00:00Z'),
  },
  loginHistory: [
    {
      id: 'l1',
      userId: 'user-1',
      ipAddress: '1.2.3.4',
      userAgent: 'ua',
      location: null,
      loginAt: new Date('2026-01-01T00:00:00Z'),
      successful: true,
    },
  ],
  notifications: [
    {
      id: 'n1',
      userId: 'user-1',
      type: 't',
      title: 'T',
      message: 'm',
      read: false,
      link: null,
      createdAt: new Date('2026-01-01T00:00:00Z'),
    },
  ],
};

const SECRET_KEYS = [
  'twoFactorSecret',
  'twoFactorEnabled',
  'firebaseUid',
  'stripeCustomerId',
  'stripeSubscriptionId',
  'stripePriceId',
  'bio',
  'phoneNumber',
];

type SelectArg = Record<string, boolean | { select?: SelectArg }> | undefined;

function applySelect(row: Record<string, unknown>, select: SelectArg): Record<string, unknown> {
  if (!select) return { ...row };
  return Object.fromEntries(
    Object.entries(select).map(([key, value]) => {
      const raw = row[key];
      if (value && typeof value === 'object') {
        const nested = value.select;
        if (Array.isArray(raw)) return [key, raw.map((r) => applySelect(r, nested))];
        return [key, raw ? applySelect(raw as Record<string, unknown>, nested) : raw];
      }
      return [key, raw];
    })
  );
}

const mocks = vi.hoisted(() => ({
  findUnique: vi.fn(),
  update: vi.fn(),
  auditCreate: vi.fn(),
  findMany: vi.fn(),
  count: vi.fn(),
  upsert: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: () => ({ value: 'session-cookie' }) })),
  headers: vi.fn(),
}));
vi.mock('@/lib/firebase/admin', () => ({ getAdminAuth: vi.fn() }));
vi.mock('@/lib/stripe/server', () => ({ getStripeServerClient: vi.fn() }));
vi.mock('@/lib/auth/verified-session', () => ({
  verifyVerifiedSessionCookie: vi.fn(async () => ({ uid: 'fb-admin' })),
}));
vi.mock('@/lib/db/client', () => ({
  db: {
    user: {
      findUnique: mocks.findUnique,
      update: mocks.update,
      findMany: mocks.findMany,
      count: mocks.count,
    },
    adminUser: { upsert: mocks.upsert },
    auditLog: { create: mocks.auditCreate },
  },
}));
vi.mock('@/lib/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

import {
  grantFreeSubscriptionAction,
  updateUserSubscriptionAction,
} from '@/app/actions/admin/subscription-actions';
import { ADMIN_USER_DETAIL_SELECT, ADMIN_USER_SELECT } from '@/lib/admin/user-select';

const ADMIN_ROW = { ...FULL_USER, id: 'admin-1', adminUser: { permissions: ['*'] } };

function expectNoSecrets(result: unknown) {
  const json = JSON.stringify(result);
  expect(json).not.toContain('JBSWY3DPEHPK3PXP');
  expect(json).not.toContain('fb-uid-secret');
  expect(json).not.toContain('cus_123');
  expect(json).not.toContain('sub_123');
  expect(json).not.toContain('price_123');
}

describe('KAN-169: admin selects and subscription actions return only selected fields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.findUnique.mockImplementation(async ({ where, select }) =>
      where.firebaseUid ? ADMIN_ROW : applySelect(FULL_USER, select)
    );
    mocks.update.mockImplementation(async ({ select }) => applySelect(FULL_USER, select));
  });

  it('the shared selects never name a secret column', () => {
    for (const key of SECRET_KEYS) {
      expect(ADMIN_USER_SELECT).not.toHaveProperty(key);
      expect(ADMIN_USER_DETAIL_SELECT).not.toHaveProperty(key);
    }
  });

  it('updateUserSubscriptionAction returns no secret fields and selects explicitly', async () => {
    const result = await updateUserSubscriptionAction('user-1', {
      subscriptionTier: 'pro',
      subscriptionStatus: 'active',
    });

    expect(result.success).toBe(true);
    for (const key of SECRET_KEYS) expect(result.data.user).not.toHaveProperty(key);
    expect(mocks.update.mock.calls[0][0].select).toBeDefined();
    expectNoSecrets(result);
  });

  it('grantFreeSubscriptionAction returns no secret fields and selects explicitly', async () => {
    const result = await grantFreeSubscriptionAction('user-1', 'pro', 30);

    expect(result.success).toBe(true);
    for (const key of SECRET_KEYS) expect(result.data.user).not.toHaveProperty(key);
    expect(mocks.update.mock.calls[0][0].select).toBeDefined();
    expectNoSecrets(result);
  });
});
