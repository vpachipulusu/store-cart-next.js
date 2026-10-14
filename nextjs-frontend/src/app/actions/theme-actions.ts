'use server';

import { unstable_cache } from 'next/cache';
import { db } from '@/lib/db/client';
import { isDatabaseConfigured } from '@/lib/db/config';
import { DEFAULT_THEME } from '@/config/themes';
import { logger } from '@/lib/logger';

/**
 * Fetch the active theme name from AppSettings.
 * Cached for 1 hour with a dedicated cache tag for revalidation.
 *
 * The root layout calls this, so it also runs while `next build` prerenders static pages. Without a
 * database (CI, secret-less image builds) it returns the default instead of querying; the page still
 * carries the 1h revalidate and the `active-theme` tag, so it picks up the stored theme at runtime.
 */
async function fetchActiveTheme(): Promise<string> {
  if (!isDatabaseConfigured()) {
    return DEFAULT_THEME;
  }

  try {
    const setting = await db.appSettings.findUnique({
      where: { key: 'active_theme' },
    });

    if (!setting?.value) {
      return DEFAULT_THEME;
    }

    const themeName = typeof setting.value === 'string' ? setting.value : String(setting.value);

    return themeName || DEFAULT_THEME;
  } catch (error) {
    // Log and rethrow so unstable_cache does not store the default for the whole revalidate window.
    logger.error('Failed to fetch active theme:', error);
    throw error;
  }
}

const getCachedActiveTheme = unstable_cache(fetchActiveTheme, ['active-theme'], {
  revalidate: 3600,
  tags: ['active-theme'],
});

export async function getActiveTheme(): Promise<string> {
  try {
    return await getCachedActiveTheme();
  } catch {
    return DEFAULT_THEME; // already logged; falls back outside the cache so it is not cached
  }
}
