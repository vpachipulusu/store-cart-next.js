'use server';

import { DEFAULT_FONT, type FontId } from '@/config/fonts';

/**
 * The active body font. The admin font setting is switched off until its API exists (KAN-184, KAN-114), so
 * the root layout always renders the default font and no database read happens here.
 */
export async function getActiveFont(): Promise<FontId> {
  return DEFAULT_FONT;
}
