'use client';

import { useEffect, useRef, useState, useTransition, type FormEvent } from 'react';
import { inviteTeamMemberAction, type InviteResult } from '@/app/actions/team-actions';
// Type-only: the module is server-only, so this import must stay erased.
import type { InviteRole } from '@/lib/api/team';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const UNEXPECTED_ERROR = 'We could not send the invitation. Please try again.';
/** "Copied" is cleared after this, so copying again is announced again. */
const COPIED_RESET_MS = 3000;

function statusText(created: InviteResult | null, copied: boolean): string {
  if (!created) return '';
  const sent = created.emailSent
    ? `Invitation sent to ${created.email}.`
    : `Invitation created for ${created.email}, but the email could not be sent. Share the link below.`;
  return copied ? `${sent} Link copied.` : sent;
}

/**
 * Invite by email (KAN-62). The accept link is shown once, right after the invitation is created, so the inviter
 * can copy it (for example when the email could not be sent). It is held in component state only.
 */
export function InviteMemberForm() {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<InviteRole>('STAFF');
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, startTransition] = useTransition();
  const linkField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (created) linkField.current?.focus();
  }, [created]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPIED_RESET_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // aria-disabled keeps the button focusable, so a second submit is ignored here.
    if (pending) return;
    setError(null);
    setCreated(null);
    setCopied(false);
    startTransition(async () => {
      try {
        const result = await inviteTeamMemberAction({ email, role });
        if (result.success) {
          setCreated(result.data);
          setEmail('');
        } else {
          setError(result.error);
        }
      } catch {
        setError(UNEXPECTED_ERROR);
      }
    });
  };

  const copy = async () => {
    if (!created) return;
    setCopied(false);
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
        <Button
          type="submit"
          aria-disabled={pending}
          className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        >
          {pending ? 'Sending…' : 'Send invitation'}
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {/* Always mounted, so screen readers announce the result and "Link copied". */}
      <p role="status" aria-live="polite" className="text-sm font-medium">
        {statusText(created, copied)}
      </p>

      {created && (
        <div className="space-y-2 rounded-lg border border-border p-4">
          <p className="text-sm text-muted-foreground">
            The link works once and expires in 7 days. It is shown only now.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              ref={linkField}
              readOnly
              aria-label="Invitation link"
              value={created.acceptUrl}
              onFocus={(event) => event.currentTarget.select()}
            />
            <Button type="button" variant="outline" onClick={copy}>
              {copied ? 'Copied' : 'Copy link'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
