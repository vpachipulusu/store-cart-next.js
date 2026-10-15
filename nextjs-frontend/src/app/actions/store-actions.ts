'use server';

import { cookies } from 'next/headers';
import { revalidatePath } from 'next/cache';
import { fetchMerchantStores } from '@/lib/api/stores';
import {
  isStoreId,
  SELECTED_STORE_COOKIE,
  STORE_NOT_AVAILABLE_MESSAGE,
  STORES_UNAVAILABLE_MESSAGE,
} from '@/lib/stores/selection';

type ActionResponse = { success: boolean; error?: string };

const SELECTED_STORE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

/**
 * Remembers which store the dashboard shows. The id is checked against the stores the backend lists for the
 * caller's session, so a forged id is rejected and the cookie only ever holds a store the user may open.
 */
export async function selectStoreAction(storeId: string): Promise<ActionResponse> {
  if (!isStoreId(storeId)) {
    return { success: false, error: STORE_NOT_AVAILABLE_MESSAGE };
  }

  const stores = await fetchMerchantStores();
  if (!stores.success) {
    return { success: false, error: STORES_UNAVAILABLE_MESSAGE };
  }
  if (!stores.data.some((store) => store.id === storeId)) {
    return { success: false, error: STORE_NOT_AVAILABLE_MESSAGE };
  }

  (await cookies()).set(SELECTED_STORE_COOKIE, storeId, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: SELECTED_STORE_MAX_AGE_SECONDS,
  });
  revalidatePath('/dashboard', 'layout');
  return { success: true };
}
