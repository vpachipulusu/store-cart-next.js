import Link from 'next/link';

import { TEXT_ACTION_CLASS } from './styles';

interface PermissionNoticeProps {
  ownerName?: string;
}

/** Shown when a staff role opens a page that is not theirs (team and billing settings, KAN-62). */
export function PermissionNotice({ ownerName }: PermissionNoticeProps) {
  const owner = ownerName ? `the owner (${ownerName})` : 'the owner';

  return (
    <div role="alert" className="rounded-xl border border-border bg-card p-4">
      <p className="text-sm font-medium text-foreground">
        You do not have access. Ask {owner} for the role.
      </p>
      <Link href="/dashboard" className={TEXT_ACTION_CLASS}>
        Back to Overview
      </Link>
    </div>
  );
}
