'use client';

import { useState, useTransition } from 'react';
import Link from 'next/link';
import { acceptInvitationAction } from '@/app/actions/team-actions';
import { Button } from '@/components/ui/button';

/** The only way to spend an invitation: an explicit click that posts the token (KAN-62). */
export function AcceptInvitationButton({ token }: { token: string }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  const accept = () => {
    setError(null);
    startTransition(async () => {
      const result = await acceptInvitationAction(token);
      if (result.success) setAccepted(true);
      else setError(result.error);
    });
  };

  if (accepted) {
    return (
      <div role="status" className="space-y-3">
        <p className="text-sm font-medium">You have joined the team.</p>
        <Button asChild>
          <Link href="/dashboard">Go to the dashboard</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button onClick={accept} disabled={pending}>
        {pending ? 'Accepting…' : 'Accept invitation'}
      </Button>
    </div>
  );
}
