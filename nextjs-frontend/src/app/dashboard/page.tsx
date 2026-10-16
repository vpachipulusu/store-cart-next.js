import { cookies } from 'next/headers';
import { redirect, unstable_rethrow } from 'next/navigation';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';
import { fetchBillingSummary, NO_BILLING_ORGANIZATION_MESSAGE } from '@/lib/api/billing';
import { fetchProfile, toProfile } from '@/lib/api/account';
import { getCurrentStoreSelection } from '@/lib/stores/current';
import { describePlanStatus } from '@/lib/billing-status';
import { INVALID_AUTHENTICATION_MESSAGE, isSessionRejected } from '@/lib/api/session-rejected';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import Link from 'next/link';
import { NeedsAttention } from '@/components/dashboard/overview/needs-attention';
import { OverviewKpiStrip } from '@/components/dashboard/overview/overview-kpi-strip';
import { OverviewPlanUsage } from '@/components/dashboard/overview/overview-plan-usage';
import { RecentOrdersPanel } from '@/components/dashboard/overview/recent-orders-panel';
import { Panel } from '@/components/dashboard/overview/panel';
import { NEW_STORE_CHECKLIST, NEW_STORE_KPI_CELLS } from '@/components/dashboard/overview/defaults';
import { SubscriptionSuccessHandler } from '@/components/dashboard/subscription-success-handler';
import { Suspense } from 'react';

// Disable caching for this page to ensure fresh subscription data
export const dynamic = 'force-dynamic';
export const revalidate = 0;

/**
 * Profile and the plan come from the API (KAN-41, KAN-45). The plan is the billing organisation's; an
 * account that manages no organisation is on the free plan. Login history lives on the security page.
 */
async function getUserData() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    await verifyVerifiedSessionCookie();

    const [profile, billing] = await Promise.all([fetchProfile(), fetchBillingSummary()]);

    // The backend rejected the session (401 "Invalid authentication"), or has no platform user for it
    // (404, a session minted before the API cutover): sign in again. Anything else is an outage, not a
    // reason to log the user out.
    if (!profile.success && isSessionRejected(profile)) {
      redirect('/api/auth/clear-session');
    }
    if (!profile.success) {
      throw new Error(`Dashboard API request failed (${profile.status ?? 'unreachable'})`);
    }
    // A 404 from billing can mean the organisation vanished mid-request, not a stale session, so only a
    // revoked session (401) clears it here; the profile call above already catches a missing platform user.
    if (!billing.success && billing.error === INVALID_AUTHENTICATION_MESSAGE) {
      redirect('/api/auth/clear-session');
    }
    // No billing organisation is the free plan; any other billing failure is an outage, not a free plan.
    if (!billing.success && billing.error !== NO_BILLING_ORGANIZATION_MESSAGE) {
      throw new Error(
        `Dashboard billing request failed (${('status' in billing && billing.status) || 'unreachable'})`
      );
    }
    const plan = billing.success ? billing.data : null;

    return {
      ...toProfile(profile.data),
      subscriptionTier: plan?.plan.key ?? 'free',
      planLimits: plan
        ? {
            maxStores: plan.plan.max_stores,
          }
        : null,
      planStatus: describePlanStatus({
        planKey: plan?.plan.key ?? 'free',
        status: plan?.subscription_status ?? 'inactive',
        periodEnd: plan?.current_period_end ?? null,
        hasSubscription: plan?.has_subscription ?? false,
      }),
    };
  } catch (error) {
    unstable_rethrow(error);
    if (isEmailNotVerifiedError(error)) {
      redirect('/verify-email');
    }
    if (isSessionVerificationError(error)) {
      // Expired/invalid session — clear cookies via route handler and redirect to login
      redirect('/api/auth/clear-session');
    }
    logRouteError('/dashboard', error);
    throw error;
  }
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  // Await searchParams as per Next.js 15 requirements
  const { upgrade } = await searchParams;

  const user = await getUserData();

  if (!user) {
    redirect('/login');
  }

  // KAN-210: a verified user with no store goes to onboarding. Only here, not in the layout (no pathname,
  // would loop and lock them out of profile/security/billing) or the proxy. A store in any status
  // (PROVISIONING, FAILED) counts, and an unreadable store list never redirects. Not straight after a checkout
  // (?upgrade=success, KAN-157): the page must render so SubscriptionSuccessHandler can confirm the upgrade;
  // the handler then returns to /dashboard, which redirects as usual. The parameter only skips this nudge, it
  // grants nothing (the handler verifies the checkout session on the server).
  const storeSelection = await getCurrentStoreSelection();
  if (upgrade !== 'success' && storeSelection.available && storeSelection.stores.length === 0) {
    redirect('/dashboard/onboarding');
  }

  // Only the store count is real: there is no merchant data API for products or staff yet.
  const usageItems =
    user.planLimits && storeSelection.available
      ? [
          {
            id: 'stores',
            label: 'Stores',
            used: storeSelection.stores.length,
            limit: user.planLimits.maxStores,
          },
        ]
      : [];

  return (
    <div className="space-y-6">
      <Suspense fallback={null}>
        <SubscriptionSuccessHandler />
      </Suspense>

      <header>
        <h1 className="text-3xl tracking-tight">Welcome back, {user.displayName || user.email}</h1>
        <p className="text-muted-foreground">Here is how your store is doing.</p>
      </header>

      <OverviewKpiStrip cells={NEW_STORE_KPI_CELLS} />

      <div className="grid gap-6 min-[1000px]:grid-cols-[1.8fr_1fr]">
        <RecentOrdersPanel state={{ status: 'empty' }} checklist={NEW_STORE_CHECKLIST} />
        <div className="space-y-6">
          <NeedsAttention items={[]} />
          <Panel title="Plan" titleId="plan-title">
            <div className="mb-3">
              <p className="text-sm font-medium capitalize">{`${user.subscriptionTier} plan`}</p>
              <p className="text-[0.8125rem] text-muted-foreground">{user.planStatus}</p>
            </div>
            <OverviewPlanUsage items={usageItems} compareHref="/pricing" />
          </Panel>
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        Your account details are in{' '}
        <Link href="/dashboard/profile" className="font-medium text-accent-ink underline">
          Profile
        </Link>
        , sign-in history and passwords in{' '}
        <Link href="/dashboard/security" className="font-medium text-accent-ink underline">
          Security
        </Link>{' '}
        and preferences in{' '}
        <Link href="/dashboard/settings" className="font-medium text-accent-ink underline">
          Settings
        </Link>
        .
      </p>
    </div>
  );
}
