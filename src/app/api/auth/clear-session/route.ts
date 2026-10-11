import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

/**
 * GET /api/auth/clear-session
 *
 * Clears stale session cookies and redirects to login.
 * Used when a Server Component detects an expired/invalid session
 * but cannot delete cookies directly.
 */
export async function GET() {
  const cookieStore = await cookies();
  cookieStore.delete('session');
  cookieStore.delete('email-verified');
  redirect('/login');
}
