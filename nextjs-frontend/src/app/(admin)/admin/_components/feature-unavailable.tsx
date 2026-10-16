import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Panel } from '@/components/dashboard/overview/panel';

type FeatureUnavailableProps = {
  title: string;
  description: string;
};

/**
 * State for admin pages that have no backend API yet (KAN-184). The page is switched off rather than left
 * reading the database directly; it returns when its API exists (KAN-114).
 */
export function FeatureUnavailable({ title, description }: FeatureUnavailableProps) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="text-muted-foreground">{description}</p>
      </div>
      <Panel title="Not available yet" titleId="admin-feature-unavailable">
        <p className="mb-4 text-sm text-muted-foreground">
          This page is switched off until its backend service is ready. Nothing is lost: it will
          return in a later release.
        </p>
        <Button variant="outline" asChild>
          <Link href="/admin/users">Go to Users</Link>
        </Button>
      </Panel>
    </div>
  );
}
