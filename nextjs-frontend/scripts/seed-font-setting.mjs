/**
 * Seed Font Setting
 *
 * This script initializes the font setting in the database
 * Run this after updating the codebase to add font configuration
 *
 * Usage: node scripts/seed-font-setting.mjs
 */

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  console.log('🎨 Seeding font setting...');

  try {
    // Check if font setting already exists
    const existingSetting = await prisma.appSettings.findUnique({
      where: { key: 'app_font' },
    });

    if (existingSetting) {
      console.log('✅ Font setting already exists:', existingSetting.value);
      return;
    }

    // Create default font setting
    const fontSetting = await prisma.appSettings.create({
      data: {
        key: 'app_font',
        value: 'inter',
        category: 'general',
        description: 'Application font family',
      },
    });

    console.log('✅ Font setting created successfully:', fontSetting.value);
    console.log(
      '\n📝 You can now change the font from the Admin Dashboard > Settings > General tab'
    );
  } catch (error) {
    console.error('❌ Error seeding font setting:', error);
    process.exit(1);
  }
}

main()
  .then(async () => {
    await prisma.$disconnect();
    console.log('\n✨ Done!');
  })
  .catch(async (error) => {
    console.error(error);
    await prisma.$disconnect();
    process.exit(1);
  });
