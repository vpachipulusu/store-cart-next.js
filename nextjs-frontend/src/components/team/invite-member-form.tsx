'use client';

import { useState, useTransition, type FormEvent } from 'react';
import { inviteTeamMemberAction, type InviteResult } from '@/app/actions/team-actions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

/**
 * Invite by email (KAN-62). The accept link is shown once, right after the invitation is created, so the inviter
 * can copy it (for example when the email could not be sent). It is held in component state only.
 */
export function InviteMemberForm() {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'STAFF' | 'ADMIN'>('STAFF');
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, startTransition] = useTransition();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setCreated(null);
    setCopied(false);
    startTransition(async () => {
      const result = await inviteTeamMemberAction({ email, role });
      if (result.success) {
        setCreated(result.data);
        setEmail('');
      } else {
        setError(result.error);
      }
    });
  };

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.acceptUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
        <div className="space-y-2">
          <Label htmlFor="invite-email">Email address</Label>
          <Input
            id="invite-email"
            type="email"
            autoComplete="off"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="invite-role">Role</Label>
          <select
            id="invite-role"
            value={role}
            onChange={(event) => setRole(event.target.value === 'ADMIN' ? 'ADMIN' : 'STAFF')}
            className="flex h-11 w-full rounded-xl border border-input bg-background px-4 text-sm shadow-sm"
          >
            <option value="STAFF">Staff</option>
            <option value="ADMIN">Admin</option>
          </select>
        </div>
        <Button type="submit" disabled={pending}>
          {pending ? 'Sending…' : 'Send invitation'}
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {created && (
        <div role="status" className="space-y-2 rounded-lg border border-border p-4">
          <p className="text-sm font-medium">
            {created.emailSent
              ? `Invitation sent to ${created.email}.`
              : `Invitation created for ${created.email}, but the email could not be sent. Share the link below.`}
          </p>
          <p className="text-sm text-muted-foreground">
            The link works once and expires in 7 days. It is shown only now.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input readOnly aria-label="Invitation link" value={created.acceptUrl} />
            <Button type="button" variant="outline" onClick={copy}>
              {copied ? 'Copied' : 'Copy link'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
