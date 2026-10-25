import type { ReactNode } from 'react';
import { PermissionNotice } from '@/components/dashboard/overview/permission-notice';
import { isStaffOnlyMember } from '@/lib/api/team';

/**
 * Server-side STAFF gate for billing settings (KAN-62). Billing shows the organisation the caller owns or
 * administers (`src/lib/api/billing.ts`), so the gate refuses exactly the callers who manage none: STAFF-only
 * members get the permission notice instead of the page. The backend refuses STAFF on every billing route anyway;
 * if the memberships cannot be read, the page renders and shows its own errors.
 */
export default async function BillingSettingsLayout({ children }: { children: ReactNode }) {
  const staffOnly = await isStaffOnlyMember();
  if (staffOnly.success && staffOnly.data) return <PermissionNotice />;
  return children;
}
