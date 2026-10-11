/**
 * Font Actions
 * Server actions for fetching configured font settings
 */

'use server';

import { unstable_cache } from 'next/cache';
import { db } from '@/lib/db/client';
import { DEFAULT_FONT, type FontId } from '@/config/fonts';
import { logger } from '@/lib/logger';

/**
 * Fetch the active font from AppSettings.
 * Cached for 1 hour with a dedicated cache tag for revalidation.
 */
async function fetchActiveFont(): Promise<FontId> {
  try {
    const setting = await db.appSettings.findUnique({
      where: { key: 'app_font' },
    });

    if (!setting?.value) {
      return DEFAULT_FONT;
    }

    const fontId = typeof setting.value === 'string' ? setting.value : String(setting.value);

    return (fontId as FontId) || DEFAULT_FONT;
  } catch (error) {
    logger.error('Failed to fetch active font:', error);
    return DEFAULT_FONT;
  }
}

export const getActiveFont = unstable_cache(fetchActiveFont, ['active-font'], {
  revalidate: 3600,
  tags: ['active-font'],
});
