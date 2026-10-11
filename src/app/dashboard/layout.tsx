import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';
import { adminAuth } from '@/lib/firebase/admin';
import { db } from '@/lib/db/client';
import Link from 'next/link';
import { LayoutDashboard } from 'lucide-react';
import { SessionProvider } from '@/components/providers/session-provider';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';

export const metadata = {
  title: 'Dashboard',
  description: 'Manage your account and settings',
};

async function getUser() {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('session')?.value;

    if (!sessionCookie) {
      return null;
    }

    const decodedClaims = await adminAuth.verifySessionCookie(sessionCookie, true);

    // Get user from database for additional data
    const dbUser = await db.user.findUnique({
      where: { firebaseUid: decodedClaims.uid },
      select: { id: true, displayName: true, avatarUrl: true },
    });

    // Get unread notification count and recent notifications
    const [unreadNotificationCount, recentNotifications] = dbUser
      ? await Promise.all([
          db.notification.count({
            where: { userId: dbUser.id, read: false },
          }),
          db.notification.findMany({
            where: { userId: dbUser.id },
            orderBy: { createdAt: 'desc' },
            take: 10,
          }),
        ])
      : [0, []];

    return {
      ...decodedClaims,
      dbDisplayName: dbUser?.displayName,
      dbAvatarUrl: dbUser?.avatarUrl,
      unreadNotificationCount,
      // Serialize Date objects to strings for client components
      recentNotifications: recentNotifications.map((n) => ({
        ...n,
        createdAt: n.createdAt.toISOString(),
      })),
    };
  } catch (error) {
    // Expired/invalid session — clear cookies via route handler and redirect to login
    redirect('/api/auth/clear-session');
  }
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser();

  if (!user) {
    redirect('/login');
  }

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

          <DashboardHeader
            user={{
              email: user.email,
              picture: user.picture,
              dbDisplayName: user.dbDisplayName,
              dbAvatarUrl: user.dbAvatarUrl,
              unreadNotificationCount: user.unreadNotificationCount,
              recentNotifications: user.recentNotifications,
            }}
          />
        </div>
      </header>
      <div className="h-px bg-gradient-to-r from-transparent via-theme-accent/15 to-transparent" />

      {/* Main Content */}
      <SessionProvider>
        <main className="flex-1">
          <div className="container py-8 lg:py-10">{children}</div>
        </main>
      </SessionProvider>
    </div>
  );
}
