import { cookies } from 'next/headers';
import Link from 'next/link';
import { redirect, unstable_rethrow } from 'next/navigation';
import { isEmailNotVerifiedError, verifyVerifiedSessionCookie } from '@/lib/auth/verified-session';
import { resolveAdminAccess } from '@/lib/api/admin-access';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import {
  LayoutDashboard,
  Users,
  Building2,
  Store,
  CreditCard,
  BarChart3,
  Search,
  Settings,
  FileText,
  Shield,
} from 'lucide-react';
import { AdminHeader } from '@/components/admin/admin-header';

/** Every /admin route is per-user (session cookie + admin check), so none can be prerendered. */
export const dynamic = 'force-dynamic';

async function loadAdminAccess(sessionCookie: string) {
  let uid: string | undefined;
  try {
    const decodedClaims = await verifyVerifiedSessionCookie(sessionCookie);
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

  const access = await loadAdminAccess(sessionCookie);

  // Outside the try so a non-admin goes straight to /dashboard and is never mistaken for a failed session.
  if (access.status !== 'admin') {
    redirect('/dashboard');
  }

  return access.viewer;
}

const navItems = [
  {
    title: 'Dashboard',
    href: '/admin',
    icon: LayoutDashboard,
  },
  {
    title: 'Users',
    href: '/admin/users',
    icon: Users,
  },
  {
    title: 'Organisations',
    href: '/admin/organizations',
    icon: Building2,
  },
  {
    title: 'Stores',
    href: '/admin/stores',
    icon: Store,
  },
  {
    title: 'Subscriptions',
    href: '/admin/subscriptions',
    icon: CreditCard,
  },
  {
    title: 'Analytics',
    href: '/admin/analytics',
    icon: BarChart3,
  },
  {
    title: 'SEO',
    href: '/admin/seo',
    icon: Search,
  },
  {
    title: 'Settings',
    href: '/admin/settings',
    icon: Settings,
  },
  {
    title: 'Audit Logs',
    href: '/admin/audit-logs',
    icon: FileText,
  },
];

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const viewer = await checkAdminAccess();

  return (
    <div className="min-h-screen bg-background">
      {/* Top Navigation Bar */}
      <div className="border-b">
        <div className="flex h-16 items-center px-6">
          <div className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-primary" />
            <span className="text-xl font-bold">Admin Portal</span>
          </div>

          <AdminHeader
            user={{
              email: viewer.email,
              displayName: viewer.displayName,
              avatarUrl: viewer.avatarUrl,
            }}
            adminRole={viewer.adminRole}
          />
        </div>
      </div>
      <div className="h-px bg-gradient-to-r from-transparent via-theme-accent/20 to-transparent" />

      <div className="flex">
        {/* Sidebar */}
        <aside className="min-h-[calc(100vh-4rem)] w-64 border-r bg-card">
          <nav className="space-y-1 p-4">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="nav-link-accent flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:border-l-2 hover:border-theme-accent/30 hover:bg-accent hover:text-accent-foreground"
              >
                <item.icon className="h-5 w-5" />
                {item.title}
              </Link>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-8">{children}</main>
      </div>
    </div>
  );
}
