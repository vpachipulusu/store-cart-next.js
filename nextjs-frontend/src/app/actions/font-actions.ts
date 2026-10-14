/**
 * Font Actions
 * Server actions for fetching configured font settings
 */

'use server';

import { unstable_cache } from 'next/cache';
import { db } from '@/lib/db/client';
import { isDatabaseConfigured } from '@/lib/db/config';
import { DEFAULT_FONT, type FontId } from '@/config/fonts';
import { logger } from '@/lib/logger';

/**
 * Fetch the active font from AppSettings.
 * Cached for 1 hour with a dedicated cache tag for revalidation.
 *
 * Like the theme, this runs during static prerender via the root layout, so it returns the default
 * without querying when no database is configured.
 */
async function fetchActiveFont(): Promise<FontId> {
  if (!isDatabaseConfigured()) {
    return DEFAULT_FONT;
  }

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
    // Log and rethrow so unstable_cache does not store the default for the whole revalidate window.
    logger.error('Failed to fetch active font:', error);
    throw error;
  }
}

const getCachedActiveFont = unstable_cache(fetchActiveFont, ['active-font'], {
  revalidate: 3600,
  tags: ['active-font'],
});

export async function getActiveFont(): Promise<FontId> {
  try {
    return await getCachedActiveFont();
  } catch {
    return DEFAULT_FONT; // already logged; falls back outside the cache so it is not cached
  }
}
