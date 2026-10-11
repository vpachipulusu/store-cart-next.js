// Test fixtures for user data

export const mockUsers = {
  regularUser: {
    id: 'user-123',
    firebaseUid: 'firebase-uid-123',
    email: 'test@example.com',
    emailVerified: true,
    displayName: 'Test User',
    subscriptionTier: 'free',
    subscriptionStatus: 'active',
    createdAt: new Date('2024-01-01'),
    updatedAt: new Date('2024-01-01'),
  },
  proUser: {
    id: 'user-456',
    firebaseUid: 'firebase-uid-456',
    email: 'pro@example.com',
    emailVerified: true,
    displayName: 'Pro User',
    subscriptionTier: 'pro',
    subscriptionStatus: 'active',
    stripeCustomerId: 'cus_123',
    stripeSubscriptionId: 'sub_123',
    createdAt: new Date('2024-01-01'),
    updatedAt: new Date('2024-01-01'),
  },
  adminUser: {
    id: 'user-789',
    firebaseUid: 'firebase-uid-789',
    email: 'admin@example.com',
    emailVerified: true,
    displayName: 'Admin User',
    subscriptionTier: 'enterprise',
    subscriptionStatus: 'active',
    createdAt: new Date('2024-01-01'),
    updatedAt: new Date('2024-01-01'),
  },
};

export const mockUserSettings = {
  id: 'settings-123',
  userId: 'user-123',
  theme: 'system',
  emailNotifications: true,
  language: 'en',
  timezone: 'UTC',
  createdAt: new Date('2024-01-01'),
  updatedAt: new Date('2024-01-01'),
};
