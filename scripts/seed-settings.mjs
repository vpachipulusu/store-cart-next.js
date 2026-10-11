/**
 * Script to seed default app settings
 * Run with: node scripts/seed-settings.mjs
 */

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const defaultSettings = [
  {
    key: 'app_name',
    value: 'SaaS Boilerplate',
    category: 'general',
    description: 'Application name displayed throughout the platform',
  },
  {
    key: 'support_email',
    value: 'support@example.com',
    category: 'general',
    description: 'Primary support contact email',
  },
  {
    key: 'default_timezone',
    value: 'UTC',
    category: 'general',
    description: 'Default timezone for the application',
  },
  {
    key: 'currency',
    value: 'USD',
    category: 'general',
    description: 'Default currency for pricing and billing',
  },
  {
    key: 'language',
    value: 'en',
    category: 'general',
    description: 'Default language for the application interface',
  },
];

const defaultFeatureFlags = [
  {
    name: 'oauth_signup',
    enabled: true,
    description: 'Allow users to sign up using OAuth providers (Google, GitHub)',
    rolloutPercentage: 100,
  },
  {
    name: 'stripe_billing',
    enabled: true,
    description: 'Enable Stripe billing and subscription management',
    rolloutPercentage: 100,
  },
  {
    name: 'two_factor_auth',
    enabled: false,
    description: 'Enable two-factor authentication for users',
    rolloutPercentage: 0,
  },
  {
    name: 'email_notifications',
    enabled: true,
    description: 'Send email notifications to users',
    rolloutPercentage: 100,
  },
  {
    name: 'beta_features',
    enabled: false,
    description: 'Enable beta features for testing',
    rolloutPercentage: 0,
  },
];

async function seedSettings() {
  console.log('🌱 Seeding app settings...\n');

  try {
    // Seed app settings
    for (const setting of defaultSettings) {
      const result = await prisma.appSettings.upsert({
        where: { key: setting.key },
        update: {
          value: setting.value,
          category: setting.category,
          description: setting.description,
        },
        create: setting,
      });
      console.log(`✅ Created/Updated setting: ${result.key}`);
    }

    console.log('\n🎌 Seeding feature flags...\n');

    // Seed feature flags
    for (const flag of defaultFeatureFlags) {
      const result = await prisma.featureFlag.upsert({
        where: { name: flag.name },
        update: {
          enabled: flag.enabled,
          description: flag.description,
          rolloutPercentage: flag.rolloutPercentage,
        },
        create: flag,
      });
      console.log(`✅ Created/Updated feature flag: ${result.name}`);
    }

    console.log('\n✨ Seeding completed successfully!');
  } catch (error) {
    console.error('❌ Error seeding settings:', error);
    process.exit(1);
  } finally {
    await prisma.$disconnect();
  }
}

seedSettings();
