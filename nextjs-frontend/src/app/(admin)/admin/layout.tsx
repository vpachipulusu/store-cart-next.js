import { cookies } from 'next/headers';
import Link from 'next/link';
import { Shield } from 'lucide-react';
import { redirect, unstable_rethrow } from 'next/navigation';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';
import { resolveAdminAccess } from '@/lib/api/admin-access';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import { AdminHeader } from '@/components/admin/admin-header';
import { AdminSidebar } from '@/components/admin/admin-sidebar';
import { AdminTabBar } from '@/components/admin/admin-tab-bar';

/** Every /admin route is per-user (session cookie + admin check), so none can be prerendered. */
export const dynamic = 'force-dynamic';

async function loadAdminAccess() {
  let uid: string | undefined;
  try {
    const decodedClaims = await verifyVerifiedSessionCookie();
    uid = decodedClaims.uid;

    const access = await resolveAdminAccess();
    // Anything but a confirmed admin is a denial: a session the backend rejects is cleared (as the dashboard
    // does, so /login does not bounce a still-set cookie back), every other failure throws so error.tsx
    // renders and the admin pages are never reached.
    if (access.status === 'session-rejected') {
      redirect('/api/auth/clear-session');
    }
    if (access.status === 'error') {
      throw new Error(access.message);
    }
    return access;
  } catch (error) {
    unstable_rethrow(error);
    if (isEmailNotVerifiedError(error)) {
      redirect('/verify-email');
    }
    if (isSessionVerificationError(error)) {
      redirect('/login');
    }
    logRouteError('/admin', error, uid);
    throw error;
  }
}

async function checkAdminAccess() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session')?.value;

  if (!sessionCookie) {
    redirect('/login');
  }

  const access = await loadAdminAccess();

  // Outside the try so a non-admin goes straight to /dashboard and is never mistaken for a failed session.
  if (access.status !== 'admin') {
    redirect('/dashboard');
  }

  return access.viewer;
}

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const viewer = await checkAdminAccess();

  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-[60] focus:flex focus:min-h-11 focus:items-center focus:rounded-md focus:border focus:border-foreground focus:bg-background focus:px-4 focus:font-medium focus:text-foreground"
      >
        Skip to main content
      </a>
      <AdminSidebar />
      <div className="flex min-h-screen flex-col min-[900px]:ps-60">
        <header className="sticky top-0 z-30 w-full border-b border-border/50 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="flex h-[72px] items-center px-6">
            {/* Below 900px the sidebar is hidden, so the header names the area. */}
            <Link
              href="/admin"
              className="flex min-h-11 items-center gap-2 text-xl font-semibold min-[900px]:hidden"
            >
              <Shield className="h-6 w-6 text-primary" aria-hidden="true" />
              Admin
            </Link>

            <AdminHeader
              user={{
                email: viewer.email,
                displayName: viewer.displayName,
                avatarUrl: viewer.avatarUrl,
              }}
              adminRole={viewer.adminRole}
            />
          </div>
        </header>
        <div
          aria-hidden="true"
          className="h-px bg-gradient-to-r from-transparent via-theme-accent/20 to-transparent"
        />

        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 p-4 pb-[calc(3.5rem+1rem+env(safe-area-inset-bottom))] focus:outline-none min-[900px]:p-8"
        >
          {children}
        </main>
      </div>
      <AdminTabBar />
    </div>
  );
}
