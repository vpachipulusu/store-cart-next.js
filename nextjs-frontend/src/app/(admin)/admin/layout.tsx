import { cookies } from 'next/headers';
import Link from 'next/link';
import { redirect, unstable_rethrow } from 'next/navigation';
import { getAdminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import {
  LayoutDashboard,
  Users,
  CreditCard,
  BarChart3,
  Search,
  Settings,
  FileText,
  Shield,
} from 'lucide-react';
import { AdminHeader } from '@/components/admin/admin-header';

/**
 * Every /admin route is per-user (session cookie + admin check) and reads Prisma, so none can be
 * prerendered. Declaring it here, before render, keeps `next build` from attempting a static render of
 * any child page and issuing its queries.
 */
export const dynamic = 'force-dynamic';

async function loadUserBySession(sessionCookie: string) {
  let uid: string | undefined;
  try {
    const decodedClaims = await getAdminAuth().verifySessionCookie(sessionCookie, true);
    uid = decodedClaims.uid;

    return await db.user.findUnique({
      where: { firebaseUid: uid },
      include: {
        adminUser: true,
      },
    });
  } catch (error) {
    unstable_rethrow(error);
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

  const user = await loadUserBySession(sessionCookie);

  // Outside the try so a non-admin goes straight to /dashboard and is never mistaken for a failed session.
  if (!user || !user.adminUser) {
    redirect('/dashboard');
  }

  return {
    user,
    adminUser: user.adminUser,
  };
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
  const { user, adminUser } = await checkAdminAccess();

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
              email: user.email,
              displayName: user.displayName,
              avatarUrl: user.avatarUrl,
            }}
            adminRole={adminUser.role}
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
