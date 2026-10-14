// @vitest-environment node
/**
 * KAN-172: the legacy subscription, notification and admin server actions must never return raw
 * Stripe/Firebase/Prisma error text to the client. Every dependency is mocked to reject with a
 * secret-looking error; each action must answer with its stable generic message, leak nothing, and
 * hand the original error (with a message string) to the logger.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Secret-looking fragments are assembled at runtime so secret scanners do not flag this file.
const STRIPE_KEY = ['sk', 'live', '51HxYzSECRETKEY0123456789'].join('_');
const JWT = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxIn0', 'c2lnbmF0dXJl'].join('.');
const DB_URL = ['postgres:', '', 'dbuser:dbpass@internal-host:5432/storecart'].join('/');
const EMAIL = 'victim.person@example.com';
const LEAK_FRAGMENTS = [STRIPE_KEY, JWT, DB_URL, EMAIL, 'dbpass', 'internal-host', 'SECRET-LEAK'];

const SECRET_ERROR = new Error(
  `SECRET-LEAK Invalid API Key ${STRIPE_KEY} for ${EMAIL} token=${JWT} at ${DB_URL}`
);

const mocks = vi.hoisted(() => {
  // Read at module load by subscription-actions; without it checkout returns its config message.
  process.env.STRIPE_PRICE_ID_PRO_MONTHLY = 'price_test_pro_monthly';
  const state = { error: undefined as unknown, resolves: new Set<string>() };
  const fail = () => Promise.reject(state.error);

  // Any property access yields another proxy; calling any of them rejects with the secret error.
  const deepRejecting = (): any =>
    new Proxy(function () {}, {
      get: (_t, prop) => (prop === 'then' ? undefined : deepRejecting()),
      apply: () => fail(),
    });

  const admin = {
    id: 'admin-1',
    email: 'admin@example.com',
    firebaseUid: 'fb-admin',
    adminUser: { id: 'a1', userId: 'admin-1', role: 'super_admin', permissions: ['*'] },
  };

  // Every model method rejects, except the admin lookup by firebaseUid used for authentication.
  const modelProxy = (model: string): any =>
    new Proxy(
      {},
      {
        get: (_t, method) => {
          if (method === 'then') return undefined;
          if (state.resolves.has(`${model}.${String(method)}`)) return () => Promise.resolve({});
          if (model === 'user' && method === 'findUnique') {
            return (args: any) => (args?.where?.firebaseUid ? Promise.resolve(admin) : fail());
          }
          return () => fail();
        },
      }
    );

  const db: any = new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'then') return undefined;
        if (typeof prop === 'string' && prop.startsWith('$')) return () => fail();
        return modelProxy(String(prop));
      },
    }
  );

  return {
    state,
    db,
    deepRejecting,
    logError: vi.fn(),
    verifySession: vi.fn(),
    getVerifiedUserId: vi.fn(),
  };
});

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: () => ({ value: 'session-cookie' }) }),
}));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn(), revalidateTag: vi.fn() }));
vi.mock('@/lib/db/client', () => ({ db: mocks.db }));
vi.mock('@/lib/stripe/server', () => ({ getStripeServerClient: () => mocks.deepRejecting() }));
vi.mock('@/lib/firebase/admin', () => ({ getAdminAuth: () => mocks.deepRejecting() }));
vi.mock('@/lib/auth/verified-session', () => ({
  getVerifiedUserId: mocks.getVerifiedUserId,
  verifyVerifiedSessionCookie: mocks.verifySession,
}));
vi.mock('@/lib/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: mocks.logError },
}));

import * as subscription from '@/app/actions/subscription-actions';
import * as notification from '@/app/actions/notification-actions';
import * as seo from '@/app/actions/admin/seo-actions';
import * as settings from '@/app/actions/admin/settings-actions';
import * as adminSubscription from '@/app/actions/admin/subscription-actions';
import * as adminUser from '@/app/actions/admin/user-actions';

type Result = { success: boolean; error?: string; data?: unknown };
type Row = [name: string, call: () => Promise<Result>, generic: string];

const SEO_META = { page: '/home', title: 'Home', description: 'The home page' };
const REDIRECT = { fromPath: '/a', toPath: '/b', statusCode: '301' as unknown as number };
const SETTING = { key: 'site.name', value: 'x', category: 'general' };
const FLAG = { name: 'beta', enabled: true };
const TEMPLATE = { name: 'welcome', subject: 'Hi', htmlBody: '<p>Hi</p>' };

const ROWS: Row[] = [
  // subscription-actions.ts (14)
  [
    'getSubscriptionStatusAction',
    () => subscription.getSubscriptionStatusAction(),
    'Failed to get subscription status',
  ],
  [
    'createCheckoutSessionAction',
    () => subscription.createCheckoutSessionAction('pro', 'monthly'),
    'Failed to create checkout session',
  ],
  [
    'verifyUpgradeSessionAction',
    () => subscription.verifyUpgradeSessionAction() as Promise<Result>,
    'Failed to verify upgrade session',
  ],
  [
    'createBillingPortalSessionAction',
    () => subscription.createBillingPortalSessionAction(),
    'Failed to create billing portal session',
  ],
  [
    'cancelSubscriptionAction',
    () => subscription.cancelSubscriptionAction(),
    'Failed to cancel subscription',
  ],
  [
    'resumeSubscriptionAction',
    () => subscription.resumeSubscriptionAction(),
    'Failed to resume subscription',
  ],
  [
    'updateSubscriptionAction',
    () => subscription.updateSubscriptionAction('price_1'),
    'Failed to update subscription',
  ],
  [
    'getSubscriptionInvoicesAction',
    () => subscription.getSubscriptionInvoicesAction(),
    'Failed to get invoices',
  ],
  [
    'getUpcomingInvoiceAction',
    () => subscription.getUpcomingInvoiceAction(),
    'Failed to get upcoming invoice',
  ],
  [
    'hasActiveSubscriptionAction',
    () => subscription.hasActiveSubscriptionAction(),
    'Failed to check subscription status',
  ],
  [
    'getSubscriptionDetailsAction',
    () => subscription.getSubscriptionDetailsAction(),
    'Failed to get subscription details',
  ],
  [
    'getPaymentMethodsAction',
    () => subscription.getPaymentMethodsAction(),
    'Failed to get payment methods',
  ],
  [
    'deletePaymentMethodAction',
    () => subscription.deletePaymentMethodAction('pm_1'),
    'Failed to delete payment method',
  ],
  [
    'setDefaultPaymentMethodAction',
    () => subscription.setDefaultPaymentMethodAction('pm_1'),
    'Failed to set default payment method',
  ],
  // notification-actions.ts (4)
  [
    'getNotificationsAction',
    () => notification.getNotificationsAction(),
    'Failed to get notifications',
  ],
  [
    'markNotificationAsReadAction',
    () => notification.markNotificationAsReadAction('n1'),
    'Failed to mark notification as read',
  ],
  [
    'markAllNotificationsAsReadAction',
    () => notification.markAllNotificationsAsReadAction(),
    'Failed to mark all notifications as read',
  ],
  [
    'deleteNotificationAction',
    () => notification.deleteNotificationAction('n1'),
    'Failed to delete notification',
  ],
  // admin/seo-actions.ts (11 single-catch sites; bulk import per-item has its own test)
  ['getAllSEOMetaAction', () => seo.getAllSEOMetaAction(), 'Failed to get SEO meta'],
  ['getSEOMetaByPageAction', () => seo.getSEOMetaByPageAction('/home'), 'Failed to get SEO meta'],
  ['upsertSEOMetaAction', () => seo.upsertSEOMetaAction(SEO_META), 'Failed to save SEO meta'],
  ['deleteSEOMetaAction', () => seo.deleteSEOMetaAction('/home'), 'Failed to delete SEO meta'],
  ['getAllURLRedirectsAction', () => seo.getAllURLRedirectsAction(), 'Failed to get URL redirects'],
  [
    'createURLRedirectAction',
    () => seo.createURLRedirectAction(REDIRECT),
    'Failed to create URL redirect',
  ],
  [
    'updateURLRedirectAction',
    () => seo.updateURLRedirectAction('r1', REDIRECT),
    'Failed to update URL redirect',
  ],
  [
    'deleteURLRedirectAction',
    () => seo.deleteURLRedirectAction('r1'),
    'Failed to delete URL redirect',
  ],
  [
    'toggleURLRedirectAction',
    () => seo.toggleURLRedirectAction('r1'),
    'Failed to toggle URL redirect',
  ],
  ['getActiveRedirectAction', () => seo.getActiveRedirectAction('/a'), 'Failed to get redirect'],
  [
    'bulkImportSEOMetaAction (outer)',
    () => seo.bulkImportSEOMetaAction([]),
    'Failed to bulk import SEO meta',
  ],
  // admin/settings-actions.ts (17 single-catch sites; bulk update per-item has its own test)
  [
    'getAllAppSettingsAction',
    () => settings.getAllAppSettingsAction(),
    'Failed to get app settings',
  ],
  [
    'getAppSettingByKeyAction',
    () => settings.getAppSettingByKeyAction('k'),
    'Failed to get app setting',
  ],
  [
    'upsertAppSettingAction',
    () => settings.upsertAppSettingAction(SETTING),
    'Failed to save app setting',
  ],
  [
    'deleteAppSettingAction',
    () => settings.deleteAppSettingAction('k'),
    'Failed to delete app setting',
  ],
  [
    'getSettingsByCategoryAction',
    () => settings.getSettingsByCategoryAction('general'),
    'Failed to get settings',
  ],
  [
    'getAllFeatureFlagsAction',
    () => settings.getAllFeatureFlagsAction(),
    'Failed to get feature flags',
  ],
  [
    'getFeatureFlagByNameAction',
    () => settings.getFeatureFlagByNameAction('beta'),
    'Failed to get feature flag',
  ],
  [
    'upsertFeatureFlagAction',
    () => settings.upsertFeatureFlagAction(FLAG),
    'Failed to save feature flag',
  ],
  [
    'toggleFeatureFlagAction',
    () => settings.toggleFeatureFlagAction('beta'),
    'Failed to toggle feature flag',
  ],
  [
    'deleteFeatureFlagAction',
    () => settings.deleteFeatureFlagAction('beta'),
    'Failed to delete feature flag',
  ],
  [
    'getAllEmailTemplatesAction',
    () => settings.getAllEmailTemplatesAction(),
    'Failed to get email templates',
  ],
  [
    'getEmailTemplateByNameAction',
    () => settings.getEmailTemplateByNameAction('welcome'),
    'Failed to get email template',
  ],
  [
    'upsertEmailTemplateAction',
    () => settings.upsertEmailTemplateAction(TEMPLATE),
    'Failed to save email template',
  ],
  [
    'deleteEmailTemplateAction',
    () => settings.deleteEmailTemplateAction('welcome'),
    'Failed to delete email template',
  ],
  ['getAuditLogsAction', () => settings.getAuditLogsAction(), 'Failed to get audit logs'],
  [
    'getSystemStatsAction',
    () => settings.getSystemStatsAction(),
    'Failed to get system statistics',
  ],
  [
    'bulkUpdateSettingsAction (outer)',
    () => settings.bulkUpdateSettingsAction([]),
    'Failed to bulk update settings',
  ],
  // admin/subscription-actions.ts (9)
  [
    'getAllSubscriptionsAction',
    () => adminSubscription.getAllSubscriptionsAction(),
    'Failed to get subscriptions',
  ],
  [
    'getSubscriptionStatsAction',
    () => adminSubscription.getSubscriptionStatsAction(),
    'Failed to get subscription statistics',
  ],
  [
    'getUserSubscriptionDetailsAction',
    () => adminSubscription.getUserSubscriptionDetailsAction('u1'),
    'Failed to get subscription details',
  ],
  [
    'updateUserSubscriptionAction',
    () =>
      adminSubscription.updateUserSubscriptionAction('u1', {
        subscriptionTier: 'pro',
        subscriptionStatus: 'active',
      }),
    'Failed to update subscription',
  ],
  [
    'cancelUserSubscriptionAction',
    () => adminSubscription.cancelUserSubscriptionAction('u1'),
    'Failed to cancel subscription',
  ],
  [
    'refundSubscriptionPaymentAction',
    () => adminSubscription.refundSubscriptionPaymentAction('u1'),
    'Failed to process refund',
  ],
  [
    'grantFreeSubscriptionAction',
    () => adminSubscription.grantFreeSubscriptionAction('u1', 'pro', 30),
    'Failed to grant subscription',
  ],
  [
    'getSubscriptionRevenueAction',
    () => adminSubscription.getSubscriptionRevenueAction(),
    'Failed to get revenue data',
  ],
  [
    'syncStripeSubscriptionsAction',
    () => adminSubscription.syncStripeSubscriptionsAction(),
    'Failed to sync subscriptions',
  ],
  // admin/user-actions.ts (10)
  ['getAllUsersAction', () => adminUser.getAllUsersAction(), 'Failed to get users'],
  ['getUserByIdAction', () => adminUser.getUserByIdAction('u1'), 'Failed to get user'],
  [
    'updateUserAction',
    () => adminUser.updateUserAction('u1', { displayName: 'Ada' }),
    'Failed to update user',
  ],
  ['deleteUserAction', () => adminUser.deleteUserAction('u1'), 'Failed to delete user'],
  [
    'grantAdminRoleAction',
    () => adminUser.grantAdminRoleAction('u1', { role: 'admin', permissions: [] }),
    'Failed to grant admin role',
  ],
  [
    'revokeAdminRoleAction',
    () => adminUser.revokeAdminRoleAction('u1'),
    'Failed to revoke admin role',
  ],
  ['getUserStatsAction', () => adminUser.getUserStatsAction(), 'Failed to get user statistics'],
  ['banUserAction', () => adminUser.banUserAction('u1', 'spam'), 'Failed to ban user'],
  ['unbanUserAction', () => adminUser.unbanUserAction('u1'), 'Failed to unban user'],
  [
    'sendUserNotificationAction',
    () => adminUser.sendUserNotificationAction('u1', { type: 'info', title: 'T', message: 'M' }),
    'Failed to send notification',
  ],
];

function expectNoLeak(value: unknown) {
  const serialised = JSON.stringify(value);
  for (const fragment of LEAK_FRAGMENTS) {
    expect(serialised).not.toContain(fragment);
  }
}

describe('KAN-172: legacy server actions return generic errors', () => {
  beforeEach(() => {
    mocks.state.error = SECRET_ERROR;
    mocks.state.resolves.clear();
    mocks.logError.mockReset();
    mocks.getVerifiedUserId.mockReset().mockResolvedValue('user-1');
    mocks.verifySession.mockReset().mockResolvedValue({ uid: 'fb-admin', email_verified: true });
  });

  it.each(ROWS)(
    '%s returns only its generic message when a dependency throws',
    async (_name, call, generic) => {
      const result = await call();

      expect(result.success).toBe(false);
      expect(result.error).toBe(generic);
      expectNoLeak(result);
    }
  );

  it.each(ROWS)('%s hands the original error to the logger', async (_name, call) => {
    await call();

    const logged = mocks.logError.mock.calls.filter((args) => args.includes(SECRET_ERROR));
    expect(logged.length).toBeGreaterThan(0);
    for (const args of logged) {
      expect(typeof args[0]).toBe('string');
      expect(args[0]).not.toContain('SECRET-LEAK');
    }
  });

  describe('unaffected responses', () => {
    it('keeps the Unauthorized string for an unauthenticated user', async () => {
      mocks.getVerifiedUserId.mockResolvedValue(null);

      const result = await subscription.getSubscriptionStatusAction();
      const notifications = await notification.getNotificationsAction();

      expect(result).toEqual({ success: false, error: 'Unauthorized' });
      expect(notifications).toEqual({ success: false, error: 'Unauthorized' });
    });

    it('keeps the zod validation message for invalid input', async () => {
      const result = await seo.upsertSEOMetaAction({ ...SEO_META, title: '' });

      expect(result.success).toBe(false);
      expect(result.error).toMatch(/at least 1 character/i);
    });
  });

  describe('bulk operations report per-item failures without raw messages', () => {
    it('bulkImportSEOMetaAction reports a generic per-item error and logs the cause', async () => {
      mocks.state.resolves.add('auditLog.create');

      const result = await seo.bulkImportSEOMetaAction([SEO_META]);

      expect(result.success).toBe(true);
      expect(result.data).toMatchObject({
        successCount: 0,
        errorCount: 1,
        errors: ['Failed to import /home'],
      });
      expectNoLeak(result);
      expect(mocks.logError).toHaveBeenCalledWith(expect.stringContaining('/home'), SECRET_ERROR);
    });

    it('bulkUpdateSettingsAction reports a generic per-item error and logs the cause', async () => {
      mocks.state.resolves.add('auditLog.create');

      const result = await settings.bulkUpdateSettingsAction([SETTING]);

      expect(result.success).toBe(true);
      expect(result.data).toMatchObject({
        successCount: 0,
        errorCount: 1,
        errors: ['Failed to update site.name'],
      });
      expectNoLeak(result);
      expect(mocks.logError).toHaveBeenCalledWith(
        expect.stringContaining('site.name'),
        SECRET_ERROR
      );
    });
  });
});
