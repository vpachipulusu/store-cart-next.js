import type { Metadata } from 'next';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { AcceptInvitationButton } from '@/components/team/accept-invitation-button';
import { isSessionVerificationError, logRouteError } from '@/lib/auth/session-errors';
import { getVerifiedSessionClaims, isEmailNotVerifiedError } from '@/lib/auth/verified-session';

/**
 * Public invitation landing page (KAN-62). Opening the link changes nothing: the invitation is spent only by the
 * explicit Accept button (a POST server action), so link prefetchers and previews cannot use it up. A signed-out
 * visitor is told to sign in and reopen the link (login does not return here yet).
 *
 * The token is in the path, so the page sends no referrer and is not indexed.
 */
export const metadata: Metadata = {
  title: 'Team invitation',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

type SessionState =
  | { kind: 'signed-in'; email: string }
  | { kind: 'signed-out' | 'expired' | 'unverified' | 'unavailable' };

async function sessionState(): Promise<SessionState> {
  try {
    const claims = await getVerifiedSessionClaims();
    return claims ? { kind: 'signed-in', email: claims.email } : { kind: 'signed-out' };
  } catch (error) {
    if (isEmailNotVerifiedError(error)) return { kind: 'unverified' };
    // A stale cookie makes the proxy send /login to /dashboard, so it is cleared first (clear-session).
    // Anything else (backend outage) must not sign the user out.
    if (isSessionVerificationError(error)) return { kind: 'expired' };
    // The route literal only: the token in the path is never logged.
    logRouteError('/invite/[token]', error);
    return { kind: 'unavailable' };
  }
}

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const session = await sessionState();

  return (
    <main
      id="main-content"
      className="flex min-h-dvh items-center justify-center bg-background px-4 py-10 text-foreground"
    >
      <div className="w-full max-w-[440px] space-y-4 rounded-xl border border-border bg-card p-6">
        <h1 className="font-display text-2xl font-semibold">Join a team on StoreCart</h1>
        {session.kind === 'signed-in' ? (
          <>
            <p className="text-sm text-muted-foreground">
              You are signed in as <strong className="text-foreground">{session.email}</strong>. The
              invitation must have been sent to this address.
            </p>
            <AcceptInvitationButton token={token} />
          </>
        ) : session.kind === 'expired' ? (
          <>
            <p className="text-sm text-muted-foreground">
              Your session has expired. Sign in again with the email address the invitation was sent
              to, then open this invitation link again.
            </p>
            <Button asChild>
              {/* A route handler, not a page: a plain link, so it is never prefetched. */}
              <a href="/api/auth/clear-session">Sign in again</a>
            </Button>
          </>
        ) : session.kind === 'unverified' ? (
          <>
            <p className="text-sm text-muted-foreground">
              Verify your email address first, then open this invitation link again.
            </p>
            <Button asChild>
              <Link href="/verify-email">Verify your email</Link>
            </Button>
          </>
        ) : session.kind === 'unavailable' ? (
          <p role="alert" className="text-sm text-muted-foreground">
            We could not check your sign-in right now. Please try again shortly by reloading this
            page.
          </p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Sign in (or create an account) with the email address the invitation was sent to, then
              open this invitation link again.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link href="/login">Sign in</Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/signup">Create an account</Link>
              </Button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
