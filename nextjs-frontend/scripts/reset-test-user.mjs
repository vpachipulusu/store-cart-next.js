#!/usr/bin/env node

/**
 * Reset Test User to Free Tier
 *
 * This script resets the test user back to free tier
 * after running subscription upgrade tests.
 *
 * Usage:
 *   node scripts/reset-test-user.mjs
 */

import { PrismaClient } from '@prisma/client';
import dotenv from 'dotenv';

// Load environment variables
dotenv.config({ path: '.env.local' });
dotenv.config();

const TEST_USER_EMAIL = process.env.TEST_USER_EMAIL || 'testuser@example.com';

const prisma = new PrismaClient();

async function resetTestUser() {
  try {
    console.log('🔄 Resetting test user to free tier...\n');

    // Find user by email
    const user = await prisma.user.findUnique({
      where: { email: TEST_USER_EMAIL },
    });

    if (!user) {
      console.log(`❌ User not found: ${TEST_USER_EMAIL}`);
      return;
    }

    console.log(`✓ Found user: ${user.id}`);

    // Reset subscription to free tier
    const updatedUser = await prisma.user.update({
      where: { id: user.id },
      data: {
        subscriptionTier: 'free',
        subscriptionStatus: 'active',
        stripeCustomerId: null,
        stripeSubscriptionId: null,
        stripePriceId: null,
        stripeCurrentPeriodEnd: null,
      },
    });

    console.log(`✓ Reset subscription tier to: ${updatedUser.subscriptionTier}`);
    console.log(`✓ Reset subscription status to: ${updatedUser.subscriptionStatus}`);
    console.log(`✓ Cleared Stripe data\n`);

    console.log('✅ Test user reset complete!\n');
    console.log('User is now ready for subscription upgrade tests:');
    console.log(`  Email: ${TEST_USER_EMAIL}`);
    console.log(`  Tier:  ${updatedUser.subscriptionTier}`);
    console.log(`  Status: ${updatedUser.subscriptionStatus}\n`);
  } catch (error) {
    console.error('❌ Error resetting test user:', error);
    throw error;
  } finally {
    await prisma.$disconnect();
  }
}

// Run the script
resetTestUser()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
