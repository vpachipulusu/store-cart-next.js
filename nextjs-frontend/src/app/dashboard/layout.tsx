import { redirect, unstable_rethrow } from 'next/navigation';
import { cookies } from 'next/headers';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';
import { fetchProfile } from '@/lib/api/account';
import { isSessionRejected } from '@/lib/api/session-rejected';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import Link from 'next/link';
import { LayoutDashboard } from 'lucide-react';
import { SessionProvider } from '@/components/providers/session-provider';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { StoreSwitcher } from '@/components/dashboard/store-switcher';
import { HideOnOnboarding } from '@/components/dashboard/hide-on-onboarding';
import { getCurrentStoreSelection } from '@/lib/stores/current';

/**
 * Every /dashboard route is per-user (session cookie) and reads the API, so none can be prerendered.
 */
export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Dashboard',
  description: 'Manage your account and settings',
};

async function getUser() {
  let uid: string | undefined;
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await verifyVerifiedSessionCookie();
    uid = decodedClaims.uid;

    // Display name and avatar come from the API (the session cookie is forwarded to the backend).
    // Notifications are switched off until KAN-114 delivers them through the API.
    const profile = await fetchProfile();
    // A session the backend rejects (or has no platform user for) is cleared so the user signs in again.
    if (!profile.success && isSessionRejected(profile)) {
      throw Object.assign(new Error('Session rejected by the backend'), {
        code: 'auth/invalid-session-cookie',
      });
    }
    if (!profile.success) {
      throw new Error(`Profile request failed (${profile.status ?? 'unreachable'})`);
    }

    return {
      email: decodedClaims.email,
      dbDisplayName: profile.data.display_name,
      dbAvatarUrl: profile.data.avatar_url,
    };
  } catch (error) {
    unstable_rethrow(error);
    // Only a failed session verification clears the session. Database and other errors are logged
    // and rethrown so error.tsx renders and the user stays signed in.
    // A verified session is required; an unverified (or stale-claim) user keeps the session and verifies first.
    if (isEmailNotVerifiedError(error)) {
      redirect('/verify-email');
    }
    if (isSessionVerificationError(error)) {
      redirect('/api/auth/clear-session');
    }
    logRouteError('/dashboard', error, uid);
    throw error;
  }
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser();

  if (!user) {
    redirect('/login');
  }

  const storeSelection = await getCurrentStoreSelection();
  const selectedStore = storeSelection.available ? storeSelection.selected : null;

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b border-border/50 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-[72px] items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="flex items-center space-x-2">
              <span className="text-xl font-semibold">Dashboard</span>
            </Link>

            <nav className="hidden items-center space-x-6 text-sm font-medium md:flex">
              <Link href="/dashboard" className="nav-link-accent text-sm font-medium">
                Home
              </Link>
              <Link href="/dashboard/profile" className="nav-link-accent text-sm font-medium">
                Profile
              </Link>
              <Link href="/dashboard/settings" className="nav-link-accent text-sm font-medium">
                Settings
              </Link>
              <Link href="/dashboard/security" className="nav-link-accent text-sm font-medium">
                Security
              </Link>
              <Link
                href="/dashboard/settings/billing"
                className="nav-link-accent text-sm font-medium"
              >
                Billing
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-4">
            {selectedStore && storeSelection.available && (
              <StoreSwitcher stores={storeSelection.stores} selectedStoreId={selectedStore.id} />
            )}
            <DashboardHeader
              user={{
                email: user.email,
                dbDisplayName: user.dbDisplayName,
                dbAvatarUrl: user.dbAvatarUrl,
              }}
            />
          </div>
        </div>
      </header>
      <div className="h-px bg-gradient-to-r from-transparent via-theme-accent/15 to-transparent" />

      {/* Main Content */}
      <SessionProvider>
        {/* data-store-id is a display and test hook for the selection preference, not an authorization boundary.
            Anything that scopes data by store must call getCurrentStoreSelection() on the server and the
            backend must authorize the store id itself (docs/developer/dashboard-store-scope.md). */}
        <main className="flex-1" data-store-id={selectedStore?.id}>
          {!storeSelection.available && (
            <div role="status" className="container pt-6 text-sm text-muted-foreground">
              Your stores could not be loaded. Reload the page to try again.
            </div>
          )}
          {storeSelection.available && !selectedStore && (
            <HideOnOnboarding>
              <div role="status" data-testid="no-stores" className="container pt-6 text-sm">
                <p className="font-medium">You do not have a store yet.</p>
                <p className="text-muted-foreground">
                  <Link
                    href="/dashboard/onboarding"
                    className="inline-flex min-h-11 items-center font-medium text-foreground underline underline-offset-4"
                  >
                    Set up your store
                  </Link>{' '}
                  to start selling.
                </p>
              </div>
            </HideOnOnboarding>
          )}
          <div className="container py-8 lg:py-10">{children}</div>
        </main>
      </SessionProvider>
    </div>
  );
}
