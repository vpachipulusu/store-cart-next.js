/**
 * Script to create an admin user
 * Run this script with: node scripts/create-admin.mjs <email>
 *
 * This script will:
 * 1. Find the user by email in Firebase
 * 2. Create an AdminUser record in the database
 * 3. Assign super_admin role with all permissions
 */

import { PrismaClient } from '@prisma/client';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const prisma = new PrismaClient();

async function createAdminUser(email) {
  try {
    // Find user by email
    const user = await prisma.user.findUnique({
      where: { email },
      include: { adminUser: true },
    });

    if (!user) {
      console.error(`❌ User with email ${email} not found`);
      console.log('\nPlease ensure the user has signed up first.');
      process.exit(1);
    }

    if (user.adminUser) {
      console.log(`⚠️  User ${email} is already an admin with role: ${user.adminUser.role}`);
      process.exit(0);
    }

    // Create admin user record
    const adminUser = await prisma.adminUser.create({
      data: {
        userId: user.id,
        role: 'super_admin',
        permissions: ['*'], // All permissions
      },
    });

    console.log('✅ Admin user created successfully!');
    console.log('\nDetails:');
    console.log(`  Email: ${user.email}`);
    console.log(`  User ID: ${user.id}`);
    console.log(`  Role: ${adminUser.role}`);
    console.log(`  Permissions: Full access (*)`);
    console.log('\nThe user can now access the admin portal at /admin');
  } catch (error) {
    console.error('❌ Error creating admin user:', error);
    process.exit(1);
  } finally {
    await prisma.$disconnect();
  }
}

// Get email from command line arguments
const email = process.argv[2];

if (!email) {
  console.error('❌ Please provide an email address');
  console.log('\nUsage: node scripts/create-admin.mjs <email>');
  console.log('Example: node scripts/create-admin.mjs admin@example.com');
  process.exit(1);
}

// Validate email format
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
if (!emailRegex.test(email)) {
  console.error('❌ Invalid email format');
  process.exit(1);
}

console.log(`Creating admin user for: ${email}\n`);
createAdminUser(email);
