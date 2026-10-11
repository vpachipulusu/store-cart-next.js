'use server';

import { unstable_cache } from 'next/cache';
import { db } from '@/lib/db/client';
import { DEFAULT_THEME } from '@/config/themes';
import { logger } from '@/lib/logger';

/**
 * Fetch the active theme name from AppSettings.
 * Cached for 1 hour with a dedicated cache tag for revalidation.
 */
async function fetchActiveTheme(): Promise<string> {
  try {
    const setting = await db.appSettings.findUnique({
      where: { key: 'active_theme' },
    });

    if (!setting?.value) {
      return DEFAULT_THEME;
    }

    const themeName =
      typeof setting.value === 'string' ? setting.value : String(setting.value);

    return themeName || DEFAULT_THEME;
  } catch (error) {
    logger.error('Failed to fetch active theme:', error);
    return DEFAULT_THEME;
  }
}

export const getActiveTheme = unstable_cache(fetchActiveTheme, ['active-theme'], {
  revalidate: 3600,
  tags: ['active-theme'],
});
