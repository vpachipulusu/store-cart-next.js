#!/usr/bin/env node

/**
 * Create Test User for E2E Subscription Tests
 *
 * This script creates a test user with free tier subscription
 * for use in end-to-end subscription upgrade tests.
 *
 * Usage:
 *   node scripts/create-test-user.mjs
 *
 * Environment Variables:
 *   TEST_USER_EMAIL - Email for test user (default: testuser@example.com)
 *   TEST_USER_PASSWORD - Password for test user (default: TestPass123!)
 */

import admin from 'firebase-admin';
import { PrismaClient } from '@prisma/client';
import dotenv from 'dotenv';

// Load environment variables
dotenv.config({ path: '.env.local' });
dotenv.config();

const TEST_USER_EMAIL = process.env.TEST_USER_EMAIL || 'testuser@example.com';
const TEST_USER_PASSWORD = process.env.TEST_USER_PASSWORD || 'TestPass123!';

const prisma = new PrismaClient();

async function initializeFirebase() {
  if (admin.apps.length === 0) {
    const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_KEY || '{}');

    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
    });
  }
  return admin.auth();
}

async function createTestUser() {
  try {
    console.log('🚀 Creating test user for E2E subscription tests...\n');

    // Initialize Firebase
    const auth = await initializeFirebase();

    // Check if user already exists
    let firebaseUser;
    try {
      firebaseUser = await auth.getUserByEmail(TEST_USER_EMAIL);
      console.log(`✓ Firebase user already exists: ${firebaseUser.uid}`);
    } catch (error) {
      // User doesn't exist, create it
      firebaseUser = await auth.createUser({
        email: TEST_USER_EMAIL,
        password: TEST_USER_PASSWORD,
        emailVerified: true,
        displayName: 'Test User',
      });
      console.log(`✓ Created Firebase user: ${firebaseUser.uid}`);
    }

    // Check if user exists in database
    let dbUser = await prisma.user.findUnique({
      where: { firebaseUid: firebaseUser.uid },
    });

    if (dbUser) {
      console.log(`✓ Database user already exists: ${dbUser.id}`);

      // Update to ensure user is on free tier
      dbUser = await prisma.user.update({
        where: { id: dbUser.id },
        data: {
          subscriptionTier: 'free',
          subscriptionStatus: 'active',
          emailVerified: true,
        },
      });
      console.log(`✓ Updated user to free tier`);
    } else {
      // Create user in database
      dbUser = await prisma.user.create({
        data: {
          firebaseUid: firebaseUser.uid,
          email: TEST_USER_EMAIL,
          emailVerified: true,
          displayName: 'Test User',
          subscriptionTier: 'free',
          subscriptionStatus: 'active',
        },
      });
      console.log(`✓ Created database user: ${dbUser.id}`);
    }

    // Create or update user settings
    const existingSettings = await prisma.userSettings.findUnique({
      where: { userId: dbUser.id },
    });

    if (!existingSettings) {
      await prisma.userSettings.create({
        data: {
          userId: dbUser.id,
          theme: 'system',
          emailNotifications: true,
          language: 'en',
          timezone: 'UTC',
        },
      });
      console.log(`✓ Created user settings`);
    }

    console.log('\n✅ Test user ready!\n');
    console.log('Credentials:');
    console.log(`  Email:    ${TEST_USER_EMAIL}`);
    console.log(`  Password: ${TEST_USER_PASSWORD}`);
    console.log(`  Tier:     ${dbUser.subscriptionTier}`);
    console.log(`  Status:   ${dbUser.subscriptionStatus}`);
    console.log('\nYou can now run subscription E2E tests:');
    console.log('  npm run test:e2e -- subscription\n');
  } catch (error) {
    console.error('❌ Error creating test user:', error);
    throw error;
  } finally {
    await prisma.$disconnect();
  }
}

// Run the script
createTestUser()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
