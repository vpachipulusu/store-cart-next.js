'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';

const ONBOARDING_PATH = '/dashboard/onboarding';

/**
 * Hides its children on the onboarding pages (KAN-60). The dashboard layout wraps every /dashboard page, so its
 * "You do not have a store yet" notice would otherwise appear above the page that is setting the store up.
 * The children are server-rendered by the layout and stay in its element tree; only their display is skipped.
 */
export function HideOnOnboarding({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const onOnboarding =
    pathname === ONBOARDING_PATH || pathname?.startsWith(`${ONBOARDING_PATH}/`) === true;
  return onOnboarding ? null : <>{children}</>;
}
