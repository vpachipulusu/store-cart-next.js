/**
 * Explicit Prisma `select` shapes for user data that admin server actions return to the browser
 * (KAN-169). Selecting columns by name keeps `twoFactorSecret`, `firebaseUid`, Stripe ids and any
 * column added to the schema later out of the response by default.
 */

/** User columns an admin may see when reading or editing a user. */
export const ADMIN_USER_SELECT = {
  id: true,
  email: true,
  emailVerified: true,
  displayName: true,
  avatarUrl: true,
  location: true,
  website: true,
  subscriptionTier: true,
  subscriptionStatus: true,
  createdAt: true,
  updatedAt: true,
  lastLoginAt: true,
} as const;

/** The admin user detail view: the safe columns plus bounded, field-limited relations. */
export const ADMIN_USER_DETAIL_SELECT = {
  ...ADMIN_USER_SELECT,
  settings: {
    select: {
      theme: true,
      emailNotifications: true,
      language: true,
      timezone: true,
    },
  },
  adminUser: {
    select: {
      id: true,
      role: true,
      permissions: true,
      createdAt: true,
    },
  },
  loginHistory: {
    select: {
      id: true,
      ipAddress: true,
      userAgent: true,
      location: true,
      loginAt: true,
      successful: true,
    },
    orderBy: { loginAt: 'desc' },
    take: 10,
  },
  notifications: {
    select: {
      id: true,
      type: true,
      title: true,
      message: true,
      read: true,
      link: true,
      createdAt: true,
    },
    orderBy: { createdAt: 'desc' },
    take: 10,
  },
} as const;

/** Subscription fields returned after an admin changes a user's plan. */
export const ADMIN_SUBSCRIPTION_USER_SELECT = {
  id: true,
  email: true,
  displayName: true,
  subscriptionTier: true,
  subscriptionStatus: true,
  stripeCurrentPeriodEnd: true,
} as const;
