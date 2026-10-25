'use client';

import { useEffect, useRef, useState, useTransition } from 'react';
import Link from 'next/link';
import { acceptInvitationAction } from '@/app/actions/team-actions';
import { Button } from '@/components/ui/button';

const UNEXPECTED_ERROR = 'We could not accept the invitation. Please try again.';

/** The only way to spend an invitation: an explicit click that posts the token (KAN-62). */
export function AcceptInvitationButton({ token }: { token: string }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [wrongAccount, setWrongAccount] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const dashboardLink = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (accepted) dashboardLink.current?.focus();
  }, [accepted]);

  const accept = () => {
    if (pending) return;
    setError(null);
    setWrongAccount(false);
    startTransition(async () => {
      try {
        const result = await acceptInvitationAction(token);
        if (result.success) {
          setAccepted(true);
        } else {
          setError(result.error);
          setWrongAccount(result.kind === 'wrong_account');
        }
      } catch {
        setError(UNEXPECTED_ERROR);
      }
    });
  };

  return (
    <div className="space-y-3">
      {/* Always mounted, so screen readers announce what changes inside it. */}
      <div role="status" aria-live="polite" className="text-sm font-medium">
        {accepted ? 'You have joined the team.' : ''}
      </div>
      {accepted ? (
        <Button asChild>
          <Link href="/dashboard" ref={dashboardLink}>
            Go to the dashboard
          </Link>
        </Button>
      ) : (
        <>
          {error && (
            <div role="alert" className="space-y-2 text-sm text-destructive">
              <p>{error}</p>
              {wrongAccount && (
                // A route handler, not a page: a plain link, so it is never prefetched.
                <a href="/api/auth/clear-session" className="font-medium underline">
                  Sign out and use another account
                </a>
              )}
            </div>
          )}
          <Button onClick={accept} aria-disabled={pending}>
            {pending ? 'Accepting…' : 'Accept invitation'}
          </Button>
        </>
      )}
    </div>
  );
}
