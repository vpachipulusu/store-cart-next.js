'use client';

import { useSessionRefresh } from '@/hooks/use-session-refresh';

export function SessionProvider({ children }: { children: React.ReactNode }) {
  useSessionRefresh();
  return <>{children}</>;
}
